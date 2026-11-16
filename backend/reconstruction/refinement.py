"""Finishing after "Terminer": recompute depth at higher resolution from the
stored originals, rebuild the volume from scratch (never on top of the live
volume), extract a master mesh, texture it, export and report."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import open3d as o3d

from .completion import NoCompletion
from .coordinates import invert_rigid
from .engine import ENGINE_VERSION, PROVISIONAL, EngineConfig, SessionEngine
from .exports import write_glb, write_mesh_ply, write_points_ply
from .fusion import SOURCE_STEREO, FusionConfig, LiveFusion
from .mesh_preview import ESTIMATED, INTERPOLATED, MEASURED, MeshConfig, supported_mesh, surface_area
from .pair_selector import select_partners
from .preview_format import encode_geometry
from .stereo_depth import combine_depths, compute_pair_depth


def footprint_width(V: np.ndarray, size_m) -> dict:
    """Heuristic container width: extent of surface above the support plane (table excluded)."""
    if len(V) == 0:
        return {"x_m": None, "z_m": None}
    top = V[:, 1] > max(0.004, 0.12 * float(V[:, 1].max()))
    if top.sum() < 20:
        return {"x_m": None, "z_m": None}
    P = V[top]
    ex = float(np.percentile(P[:, 0], 99.5) - np.percentile(P[:, 0], 0.5))
    ez = float(np.percentile(P[:, 2], 99.5) - np.percentile(P[:, 2], 0.5))
    return {"x_m": ex, "z_m": ez}


def texture_mesh(V, T, views, tex_size: int = 2048, max_views: int = 24):
    """UV atlas + projection of calibrated images (Open3D). Returns (uv per vertex, texture BGR) or raises."""
    tm = o3d.t.geometry.TriangleMesh()
    tm.vertex.positions = o3d.core.Tensor(V.astype(np.float32))
    tm.triangle.indices = o3d.core.Tensor(T.astype(np.int32))
    tm.compute_uvatlas(size=tex_size)
    step = max(1, len(views) // max_views)
    sel = views[::step][:max_views]
    imgs = [o3d.t.geometry.Image(np.ascontiguousarray(v.image[:, :, ::-1])) for v in sel]
    Ks = [o3d.core.Tensor(v.K.astype(np.float64)) for v in sel]
    Es = [o3d.core.Tensor(invert_rigid(v.T_obj_from_cam).astype(np.float64)) for v in sel]
    albedo = tm.project_images_to_albedo(imgs, Ks, Es, tex_size, True)
    tex = np.asarray(albedo.as_tensor().numpy())
    tri_uv = tm.triangle["texture_uvs"].numpy()  # (M, 3, 2) per-corner
    # glTF needs per-vertex UVs: split vertices per triangle corner.
    return tri_uv, tex[:, :, ::-1].copy() if tex.shape[2] == 3 else cv2.cvtColor(tex, cv2.COLOR_RGBA2BGR), len(sel)


def finish_session(engine: SessionEngine, out_dir: Path, finish_width: int = 960, reference_width_m: float | None = None,
                   texture: bool = True, emit: Callable[[dict], None] | None = None) -> dict:
    emit = emit or (lambda e: None)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    timings = {}
    cfg = replace(engine.cfg, preview_width=finish_width, max_partners=3,
                  fusion=FusionConfig(voxel_m=0.002, point_voxel_m=0.002, trunc_voxels=4.0))
    cfg.stereo = replace(cfg.stereo, max_disparities=384)
    fin = SessionEngine(engine.dir, engine.box, cfg)
    usable = [fid for fid, r in sorted(engine.frames.items())
              if r.epoch == engine.box.epoch and r.reason not in ("tracking_not_normal", "blurred", "image_decode_failed")]
    for fid in usable:
        r = engine.frames[fid]
        fin.add_frame(r.meta, r.image_path, r.depth_path, r.conf_path, r.received_at)
    cands = fin._candidates()
    fusion = fin.fusion
    pair_stats = {"ok": 0, "rejected": 0}
    for k, fid in enumerate(usable):
        ref = fin._view(fid)
        if cfg.use_lidar and fin.frames[fid].depth_path is not None:
            fin._integrate_lidar(fin.frames[fid], ref)
            continue
        partners = select_partners(fid, cands, engine.box.size_m, cfg.max_partners, cfg.limits)
        depths = []
        for g in partners:
            res = compute_pair_depth(ref, fin._view(g.other_id), engine.box.size_m, cfg.stereo)
            pair_stats["ok" if res.depth is not None else "rejected"] += 1
            if res.depth is not None:
                depths.append(res.depth)
        if depths:
            d, sup = combine_depths(depths)
            fusion.integrate(fid, ref.image, d, ref.K, ref.T_obj_from_cam, sup, SOURCE_STEREO)
        if k % 5 == 0:
            emit({"type": "finish_progress", "step": "depth", "done": k + 1, "total": len(usable)})
    timings["depth_s"] = time.perf_counter() - t0
    emit({"type": "finish_progress", "step": "mesh", "done": 0, "total": 1})
    t1 = time.perf_counter()
    xyz, rgb, nframes, sup, src = fusion.measured_points()
    pcls = np.where((nframes >= 2) | (sup >= 2), MEASURED, PROVISIONAL).astype(np.uint8)
    mcfg = MeshConfig(support_radius_m=0.003, interp_radius_m=0.006, min_component_triangles=150, max_triangles=250000)
    V, C, N, cls, T = supported_mesh(fusion.extract_mesh(), engine.box.size_m, xyz, nframes, mcfg)
    timings["mesh_s"] = time.perf_counter() - t1
    completion = NoCompletion().propose(V, T, cls, engine.box.size_m)
    write_points_ply(out_dir / "points.ply", xyz, rgb, pcls, nframes)
    write_mesh_ply(out_dir / "mesh.ply", V, C, N, cls, T)
    tex_info = {"status": "not_requested"}
    glb_extras = {"frame": "object", "units": "m", "up": "+y", "provenance_classes": {"0": "measured", "1": "interpolated", "2": "estimated"}}
    if len(T):
        if texture:
            emit({"type": "finish_progress", "step": "texture", "done": 0, "total": 1})
            t2 = time.perf_counter()
            try:
                views = [fin._view(f) for f in fusion.integrated_frames]
                tri_uv, tex, nv = texture_mesh(V, T, views)
                Vs = V[T.reshape(-1)]
                Ns = N[T.reshape(-1)]
                Ps = cls[T.reshape(-1)]
                Ts = np.arange(len(Vs), dtype=np.uint32).reshape(-1, 3)
                write_glb(out_dir / "model.glb", Vs, Ts, Ns, uv=tri_uv.reshape(-1, 2), texture_bgr=tex, provenance=Ps, extras=glb_extras)
                cv2.imwrite(str(out_dir / "texture.png"), tex)
                tex_info = {"status": "ok", "views": nv, "size": int(tex.shape[0]), "seconds": time.perf_counter() - t2}
            except Exception as exc:  # documented fallback: vertex colours
                tex_info = {"status": "failed_fallback_vertex_colors", "error": repr(exc)}
        if tex_info["status"] != "ok":
            write_glb(out_dir / "model.glb", V, T, N, colors=C, provenance=cls.astype(np.float32), extras=glb_extras)
        write_glb(out_dir / "model_vertexcolor.glb", V, T, N, colors=C, provenance=cls.astype(np.float32), extras=glb_extras)
    # Final inspectable geometry for the phone (decimated if needed).
    disp = (V, C, N, cls, T)
    if len(T) > 150000:
        m = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(V), o3d.utility.Vector3iVector(T.astype(np.int32)))
        m.vertex_colors = o3d.utility.Vector3dVector(C / 255.0)
        m = m.simplify_quadric_decimation(150000)
        m.compute_vertex_normals()
        from .mesh_preview import classify_vertices
        Vd = np.asarray(m.vertices)
        cd = classify_vertices(Vd, xyz, nframes, mcfg)
        cd[cd == 255] = INTERPOLATED
        disp = (Vd.astype(np.float32), (np.asarray(m.vertex_colors) * 255).astype(np.uint8), np.asarray(m.vertex_normals, np.float32), cd, np.asarray(m.triangles, np.uint32))
    fw = footprint_width(V, engine.box.size_m)
    scale = None
    if reference_width_m:
        meas = max(v for v in fw.values() if v is not None) if any(fw.values()) else None
        scale = {"reference_width_m": reference_width_m, "measured_width_m": meas,
                 "error_pct": None if meas is None else 100.0 * (meas - reference_width_m) / reference_width_m}
    areas = {"measured_m2": surface_area(V, T, cls, MEASURED), "interpolated_m2": surface_area(V, T, cls, INTERPOLATED),
             "estimated_m2": surface_area(V, T, cls, ESTIMATED)}
    sel = slice(None) if len(xyz) <= 150000 else np.linspace(0, len(xyz) - 1, 150000).astype(np.int64)
    header = {"schema": "dishplay.geometry/1", "engine": ENGINE_VERSION, "version": 1_000_000 + engine.version, "kind": "final",
              "frame": "object", "units": "m", "box_revision": engine.box.revision, "epoch": engine.box.epoch,
              "box_size_m": list(engine.box.size_m), "computed_at": time.time(), "last_frame_ids": fusion.integrated_frames[-5:],
              "integrated_frames": len(fusion.integrated_frames), "received_frames": len(engine.frames),
              "measured_points": int(len(xyz)), "confirmed_points": int((pcls == MEASURED).sum()), "surface": areas,
              "coverage": fin.coverage()}
    (out_dir / "final_preview.dpg").write_bytes(encode_geometry(header, xyz[sel], np.concatenate([rgb, pcls[:, None]], 1)[sel],
                                                               disp[0], np.concatenate([disp[1], disp[3][:, None]], 1), disp[2], disp[4]))
    report = {
        "schema": "dishplay.report/1", "engine": ENGINE_VERSION, "finish_width": finish_width,
        "frames_used": len(usable), "frames_integrated_final": len(fusion.integrated_frames),
        "pairs": pair_stats, "points": int(len(xyz)), "confirmed_points": int((pcls == MEASURED).sum()),
        "mesh": {"vertices": int(len(V)), "triangles": int(len(T)), "surface": areas,
                 "provenance_vertices": {"measured": int((cls == MEASURED).sum()), "interpolated": int((cls == INTERPOLATED).sum()),
                                         "estimated": int((cls == ESTIMATED).sum())}},
        "completion": {"provider": "none", "applied": completion is not None},
        "texture": tex_info, "footprint_width": fw, "scale_check": scale,
        "live": engine.metrics(), "snapshots": engine.snapshot_log, "timings_s": {**timings, "total": time.perf_counter() - t0},
        "notes": [
            "Global pose refinement (bundle adjustment) is NOT implemented in P1; per-pair relative pose verification/correction only.",
            "Underside in contact with the table is never observed and is not completed.",
            "Holes are left open: no hole filling, no watertight closing.",
        ],
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=float))
    manifest = {"schema": "dishplay.manifest/1", "files": sorted(p.name for p in out_dir.iterdir() if p.is_file() and p.name != "manifest.json"),
                "frame": "object (box): origin centre of box base, +y up, metres", "engine": ENGINE_VERSION,
                "box": {"T_world_from_object": engine.box.T_world_from_object.reshape(-1).tolist(), "size_m": list(engine.box.size_m),
                        "epoch": engine.box.epoch, "revision": engine.box.revision}}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    emit({"type": "finish_progress", "step": "done", "done": 1, "total": 1})
    return report
