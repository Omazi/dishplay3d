#!/usr/bin/env python3
"""Quality benchmark on the hard synthetic bowl (tests/realistic.py). Prints metrics for the last
live preview and for the finished model, and renders both. Used to compare engine changes.

  python tools/bench_quality.py --out /tmp/bench [--frames 110] [--no-finish] [--texture]

The automatic check (GitHub, when the engine changes) runs it with --texture --check tools/bench_reference.json:
the figures of the finished model are compared with the last accepted ones, and a figure that got worse by
more than its margin fails the check. After a change that moves them on purpose, the reference is written
again with --write-reference and the new figures are read in its diff.
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
        meas, interp, est = cls == 0, cls == 1, cls == 2
        if est.any():
            extra = {"estimated_vertices_pct": float(est.mean() * 100), "estimated_median_mm": float(np.median(d[est]) * 1000),
                     "estimated_p90_mm": float(np.percentile(d[est], 90) * 1000)}
        extra = {**extra, "measured_vertices_pct": float(meas.mean() * 100),
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


def texture_metrics(scene, glb_path: Path) -> dict:
    """How close the texture of the delivered model is to the true colours of the scene, at the vertices that
    were reconstructed (what was added by estimation has no true colour to compare with)."""
    import open3d as o3d
    from reconstruction.exports import glb_accessor, read_glb
    js, b = read_glb(glb_path)
    at = js["meshes"][0]["primitives"][0]["attributes"]
    if "TEXCOORD_0" not in at or not js.get("images"):
        return {"textured": False}
    P = glb_accessor(js, b, at["POSITION"]).astype(np.float64)
    N = glb_accessor(js, b, at["NORMAL"]).astype(np.float64)
    UV = glb_accessor(js, b, at["TEXCOORD_0"]).astype(np.float64)
    keep = glb_accessor(js, b, at["_PROVENANCE"]).reshape(-1) < 1.5
    P, N, UV = P[keep], N[keep], UV[keep]
    view = js["bufferViews"][js["images"][0]["bufferView"]]
    tex = cv2.imdecode(np.frombuffer(b[view["byteOffset"]: view["byteOffset"] + view["byteLength"]], np.uint8), 1)
    H, W = tex.shape[:2]
    seen = tex[np.clip((UV[:, 1] * (H - 1)).round().astype(int), 0, H - 1),
               np.clip((UV[:, 0] * (W - 1)).round().astype(int), 0, W - 1)][:, ::-1].astype(np.float64)
    org = P + N * 0.006
    ans = scene.scene.cast_rays(o3d.core.Tensor(np.concatenate([org, -N], 1).astype(np.float32)))
    t = ans["t_hit"].numpy()
    hit = np.isfinite(t) & (t < 0.02)
    geom = ans["geometry_ids"].numpy()
    mat = np.zeros(len(geom), int)
    for gid, k in scene.ids.items():
        mat[geom == gid] = k
    X = org - N * np.where(hit, t, 0)[:, None]
    light = np.array([0.25, 1.0, 0.3]) / np.linalg.norm([0.25, 1.0, 0.3])      # same shading as BowlScene.render
    truth = np.clip(scene._color(X, mat) * (0.5 + 0.5 * np.abs(ans["primitive_normals"].numpy().astype(np.float64) @ light))[:, None], 0, 1) * 255
    err = np.abs(seen[hit] - truth[hit]).mean(1)
    darker = seen[hit].sum(1) < 0.6 * truth[hit].sum(1)
    return {"textured": True, "vertices_compared": int(hit.sum()), "colour_error_mean": float(err.mean()),
            "colour_error_p90": float(np.percentile(err, 90)), "colour_error_over_40_pct": float((err > 40).mean() * 100),
            "much_darker_than_the_scene_pct": float(darker.mean() * 100)}


# The figures of the finished model watched by the automatic check: where each one is in bench.json, whether a
# higher (+1) or a lower (-1) value is better, and how far it may move for the worse before the check fails. The
# bench is the same scene and the same script each time: on one machine it repeats to the third decimal, and
# the margins leave room for another processor.
WATCHED = [
    ("completeness_pct", ("final", "completeness_pct(<4mm)"), +1, 1.5),
    ("wall_completeness_pct", ("final", "wall_completeness_pct"), +1, 2.5),
    ("measured_vertices_pct", ("final", "measured_vertices_pct"), +1, 2.0),
    ("accuracy_median_mm", ("final", "accuracy_median_mm"), -1, 0.1),
    ("accuracy_p90_mm", ("final", "accuracy_p90_mm"), -1, 0.4),
    ("floaters_pct", ("final", "floaters_pct(>6mm)"), -1, 0.8),
    ("texture_error_mean", ("texture", "colour_error_mean"), -1, 0.8),
    ("texture_error_p90", ("texture", "colour_error_p90"), -1, 2.5),
    ("texture_much_darker_pct", ("texture", "much_darker_than_the_scene_pct"), -1, 0.8),
]


def watched_figures(res: dict) -> dict:
    """The watched figures of one run; a figure the run did not produce is left out."""
    out = {}
    for name, (block, key), _, _ in WATCHED:
        value = res.get(block, {}).get(key)
        if isinstance(value, (int, float)):
            out[name] = round(float(value), 3)
    return out


def compare_with_reference(res: dict, reference: dict) -> tuple[list[str], list[str]]:
    """(one line per watched figure, the names of those that got worse by more than their margin)."""
    now, before = watched_figures(res), reference.get("figures", {})
    lines, worse = [], []
    for name, _, better, margin in WATCHED:
        if name not in before:
            continue
        if name not in now:
            lines.append(f"  {name:26} reference {before[name]:8.3f}   not measured in this run")
            worse.append(name)
            continue
        change = (now[name] - before[name]) * better          # positive: better than the reference
        mark = "WORSE" if change < -margin else ("better" if change > margin else "same")
        if mark == "WORSE":
            worse.append(name)
        lines.append(f"  {name:26} reference {before[name]:8.3f}   now {now[name]:8.3f}   margin {margin:<5} {mark}")
    return lines, worse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", default="", help="compare the finished model with this reference file; exit code 1 when a figure got worse")
    ap.add_argument("--write-reference", default="", help="write the watched figures of this run to this file")
    ap.add_argument("--out", default="/tmp/bench")
    ap.add_argument("--frames", type=int, default=110)
    ap.add_argument("--no-finish", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-refine", action="store_true", help="skip the global pose refinement when finishing")
    ap.add_argument("--jitter-mm", type=float, default=0.0, help="independent per-frame position noise on reported poses")
    ap.add_argument("--jitter-deg", type=float, default=0.0, help="independent per-frame rotation noise on reported poses")
    ap.add_argument("--no-close", action="store_true", help="do not close the surface when finishing")
    ap.add_argument("--dump", action="store_true", help="save the raw fused mesh and the point store for offline experiments")
    ap.add_argument("--mono-oracle", action="store_true",
                    help="fill stereo gaps from a SIMULATED single-image depth (true depth, damaged): upper bound of the fill step, not a result of the real network")
    ap.add_argument("--mono-distortion", type=float, default=0.03, help="slow relative error of the simulated prediction")
    ap.add_argument("--mono-model", default="", help="path of the real ONNX depth model: fill stereo gaps with it")
    ap.add_argument("--texture", action="store_true",
                    help="also texture the finished model and compare its colours with the true colours of the scene")
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
    mono, true_depths = None, {}
    if a.mono_oracle:
        from reconstruction.mono_depth import OracleMono
        mono = OracleMono(true_depths, seed=a.seed, distortion=a.mono_distortion)
    elif a.mono_model:
        from reconstruction.mono_depth import MonoDepth
        mono = MonoDepth(Path(a.mono_model))
    eng.mono = mono
    t0 = time.perf_counter()
    last = None
    for i, (Tr, Tt) in enumerate(zip(rep, true)):
        img, true_depths[i] = sc.render(Tt)
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
        rep_final = finish_session(eng, out / "final", texture=a.texture, refine=not a.no_refine, remove_table=False, mono=mono, close=not a.no_close)
        res["pose_refinement"] = rep_final["pose_refinement"]
        res["mono_fill_final"] = rep_final["mono_fill"]
        res["frames_final"] = {k: rep_final[k] for k in ("frames_available", "frames_used", "frames_integrated_final")}
        res["points_final"] = {k: rep_final[k] for k in ("points", "confirmed_points")}
        res["pairs_final"] = rep_final["pairs"]
        if a.texture:
            res["texture"] = {**{k: v for k, v in rep_final["texture"].items() if k != "usdz"}, **texture_metrics(sc, out / "final" / "model.glb")}
        for k in ("verdict", "fallbacks"):      # engines before p1-0.11.0 do not give them
            if k in rep_final:
                res[k] = rep_final[k]
        gf = decode_geometry((out / "final" / "final_preview.dpg").read_bytes())
        res["final"] = metrics(sc, gf["verts"].astype(np.float64), gf["tris"], vis_pts, vis_mat, gf["vert_rgbc"][:, 3])
        res["finish_seconds"] = time.perf_counter() - t1
    (out / "bench.json").write_text(json.dumps(res, indent=1, default=float))
    for k in ("live", "final"):
        if k in res:
            print(k, json.dumps({a: (round(b, 2) if isinstance(b, float) else b) for a, b in res[k].items()}))
    if "pose_refinement" in res:
        print("pose_refinement", {k: (round(v, 2) if isinstance(v, float) else v) for k, v in res["pose_refinement"].items()})
    for k in ("frames_final", "points_final", "pairs_final", "texture", "verdict", "fallbacks"):
        if k in res:
            print(k, json.dumps(res[k], default=float) if not isinstance(res[k], dict)
                  else json.dumps({a: (round(b, 3) if isinstance(b, float) else b) for a, b in res[k].items()}, default=float))
    print("mono_fill live", res["engine_metrics"]["mono_fill"], "final", res.get("mono_fill_final"))
    print("frames", res["engine_metrics"]["frames"], "live_s", round(live_s, 1), "finish_s", round(res.get("finish_seconds", 0), 1))
    if a.write_reference:
        from reconstruction.engine import ENGINE_VERSION
        reference = {"engine": ENGINE_VERSION, "frames": a.frames, "seed": a.seed, "figures": watched_figures(res)}
        Path(a.write_reference).write_text(json.dumps(reference, indent=1) + "\n")
        print(f"reference written to {a.write_reference}")
    if a.check:
        reference = json.loads(Path(a.check).read_text())
        lines, worse = compare_with_reference(res, reference)
        print(f"against the reference of engine {reference.get('engine')} ({a.check}):")
        print("\n".join(lines))
        if worse:
            sys.exit(f"the finished model got worse on: {', '.join(worse)}. If this is intended, write the reference again "
                     "with --write-reference and say why in the commit.")
        print("no watched figure got worse")


if __name__ == "__main__":
    main()
