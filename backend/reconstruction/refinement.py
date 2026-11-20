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

from .closure import close_surface
from .delivery import decimate_for_web, trim_ragged_border, weld_corners
from .completion import NoCompletion
from .coordinates import invert_rigid, scale_intrinsics
from .engine import ENGINE_VERSION, PROVISIONAL, EngineConfig, SessionEngine
from .exports import write_glb, write_mesh_ply, write_points_ply, write_usdz
from .fusion import FusionConfig
from .mesh_preview import (ESTIMATED, INTERPOLATED, MEASURED, DishFootprint, MeshConfig, crop_mesh, distinct_triangles, drop_small_pieces,
                           edge_manifold_triangles, supported_mesh, surface_area)
from .preview_format import encode_geometry
from .stereo_depth import View


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


def _paint_plain(tex: np.ndarray, base: np.ndarray, pts: np.ndarray, plain: np.ndarray) -> int:
    """Give the triangles marked `plain` their plain surface colour (taken from `base`) in the atlas, whatever
    the photographs projected there. Returns the number of texels repainted."""
    mask = np.zeros(tex.shape[:2], np.uint8)
    for k in np.nonzero(plain)[0]:
        cv2.fillConvexPoly(mask, pts[k], 255, lineType=cv2.LINE_8, shift=2)
    sel = (cv2.dilate(mask, np.ones((3, 3), np.uint8)) > 0) & (base.sum(2) > 0)   # with the texel border of each triangle
    tex[sel] = base[sel]
    return int(sel.sum())


def texture_mesh(V, T, views, tex_size: int = 2048, max_views: int = 36, colors_bgr: np.ndarray | None = None,
                 plain: np.ndarray | None = None):
    """UV atlas + projection of calibrated images (Open3D).

    Returns (per-corner uv in glTF convention, texture BGR, views used, fraction filled from vertex colours)."""
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
    tex = tex[:, :, ::-1].copy() if tex.shape[2] == 3 else cv2.cvtColor(tex, cv2.COLOR_RGBA2BGR)
    tri_uv = tm.triangle["texture_uvs"].numpy().astype(np.float64)  # (M, 3, 2) per corner, v pointing UP (Open3D)
    h, w = tex.shape[:2]
    # Texels that no selected image reached stay black in Open3D's result. Fill them with the fused
    # colour of their triangle (measured vertex colours), so the model has no black patches.
    base = np.zeros_like(tex)
    px = np.stack([tri_uv[:, :, 0] * (w - 1), (1.0 - tri_uv[:, :, 1]) * (h - 1)], -1)
    tri_col = colors_bgr[T].mean(1) if colors_bgr is not None else None
    filled = 0.0
    if tri_col is not None:
        pts = np.round(px * 4).astype(np.int32)
        for k in range(len(pts)):
            cv2.fillConvexPoly(base, pts[k], tri_col[k].tolist(), lineType=cv2.LINE_8, shift=2)
        unprojected = tex.sum(2) < 15
        filled = float(unprojected[base.sum(2) > 0].mean()) if (base.sum(2) > 0).any() else 0.0
        tex[unprojected] = base[unprojected]
        if plain is not None and plain.any():
            # The base under the dish faces the table: no photograph shows it, and what the projection puts
            # there comes from views that grazed it through a gap (grey streaks on a real capture).
            _paint_plain(tex, base, pts, plain)
    # glTF texture coordinates have their origin at the TOP-left of the image: flip v.
    uv = tri_uv.copy()
    uv[:, :, 1] = 1.0 - uv[:, :, 1]
    return uv, tex, len(sel), filled


def _texture_views(fin: SessionEngine, frame_ids: list[int], max_views: int = 36) -> list[View]:
    """The views that paint the texture, at the resolution of the stored photographs (the depth was computed
    on reduced images; the texture need not be)."""
    step = max(1, len(frame_ids) // max_views)
    out = []
    for f in frame_ids[::step][:max_views]:
        v = fin._view(f)
        img = cv2.imread(str(fin.frames[f].image_path), cv2.IMREAD_COLOR)
        if img is None or img.shape[1] <= v.image.shape[1]:
            out.append(v)
            continue
        K = scale_intrinsics(v.K, (v.image.shape[1], v.image.shape[0]), (img.shape[1], img.shape[0]))
        out.append(View(f, img, K, v.T_obj_from_cam))
    return out


def spread_subset(engine: SessionEngine, frame_ids: list[int], max_frames: int) -> list[int]:
    """At most max_frames views, spread as evenly as possible around the dish.

    A long scan can hold several hundred views, most of them near-duplicates of their neighbours:
    finishing them all multiplies the waiting time without adding information. Views are picked one
    by one, each time the one farthest from those already chosen (camera position in the box frame).
    """
    if max_frames <= 0 or len(frame_ids) <= max_frames:
        return list(frame_ids)
    C = np.stack([engine._geometry(f)[0][:3, 3] for f in frame_ids])
    chosen = [0]
    d = np.linalg.norm(C - C[0], axis=1)
    for _ in range(max_frames - 1):
        k = int(np.argmax(d))
        chosen.append(k)
        d = np.minimum(d, np.linalg.norm(C - C[k], axis=1))
    return [frame_ids[i] for i in sorted(chosen)]


def finish_session(engine: SessionEngine, out_dir: Path, finish_width: int = 1152, reference_width_m: float | None = None,
                   texture: bool = True, emit: Callable[[dict], None] | None = None, refine: bool = True,
                   remove_table: bool = True, max_frames: int = 140, mono=None, mono_reason: str = "",
                   close: bool = True, clean: bool = True, web_triangles: int = 60000) -> dict:
    emit = emit or (lambda e: None)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    timings = {}
    cfg = replace(engine.cfg, preview_width=finish_width, max_partners=3, confirm_min_views=2, confirm_lag=4,
                  confirm_window=16, confirm_neighbours=6, view_cache=96, anchor_live=False,   # poses: refined all together below
                  fusion=FusionConfig(voxel_m=0.002, point_voxel_m=0.002, trunc_voxels=3.0))
    cfg.stereo = replace(cfg.stereo, max_disparities=384, coarse_fill=True)
    progress = {"done": 0}

    def fin_emit(ev):
        if ev.get("type") == "frame" and ev.get("status") in ("integrated", "rejected"):
            progress["done"] += 1
            emit({"type": "finish_progress", "step": "depth", "done": min(progress["done"], len(usable)), "total": len(usable)})

    fin = SessionEngine(engine.dir, engine.box, cfg, emit=fin_emit)
    fin.mono = mono   # learned depth for what stereo cannot measure (uniform or shiny surfaces); None = off
    usable = [fid for fid, r in sorted(engine.frames.items())
              if r.epoch == engine.box.epoch and r.reason not in ("tracking_not_normal", "blurred", "image_decode_failed")]
    available = len(usable)
    usable = spread_subset(engine, usable, max_frames)
    engine.views.clear()   # the live engine's decoded images are no longer needed: free the memory
    for fid in usable:
        r = engine.frames[fid]
        fin.add_frame(r.meta, r.image_path, r.depth_path, r.conf_path, r.received_at)
    # Global pose refinement: remove the tracking drift accumulated over the tour before computing depth.
    pose_info = {"applied": False, "reason": "disabled"}
    if refine and len(usable) >= 6:
        emit({"type": "finish_progress", "step": "poses", "done": 0, "total": 1})
        try:
            from .bundle import refine_poses
            ba_views = {}
            for fid in usable:
                try:
                    ba_views[fid] = fin._view(fid)
                except ValueError:
                    pass
            res = refine_poses(ba_views, engine.box.size_m, cfg.stereo)
            del ba_views
            pose_info = {"applied": res.applied, **res.info}
            if res.applied:
                fin.pose_overrides = res.poses
                for fid, v in fin.views.items():
                    if fid in res.poses:
                        v.T_obj_from_cam = res.poses[fid]
        except Exception as exc:  # never lose a scan because the refinement failed: ARKit poses are kept
            pose_info = {"applied": False, "reason": "error", "error": repr(exc)}
    timings["poses_s"] = time.perf_counter() - t0
    # Every frame is known in advance: partners and confirming views come from both sides in time.
    fin.process_pending(live=False)
    fin.process_pending(live=False)   # second chance for frames whose first pair failed
    fin.flush()
    fusion = fin.fusion
    pair_stats = {"ok": sum(p["status"] == "ok" for p in fin.pair_reports),
                  "rejected": sum(p["status"] != "ok" for p in fin.pair_reports), "confirmation": dict(fin.confirm_stats)}
    timings["depth_s"] = time.perf_counter() - t0
    emit({"type": "finish_progress", "step": "mesh", "done": 0, "total": 1})
    t1 = time.perf_counter()
    xyz, rgb, nframes, sup, src = fusion.measured_points()
    weak = fusion.weak_cells()
    pcls = np.where((nframes >= 2) | (sup >= 2), MEASURED, PROVISIONAL).astype(np.uint8)
    pcls[weak] = INTERPOLATED
    mcfg = MeshConfig(support_radius_m=0.003, interp_radius_m=0.006, min_component_triangles=150, max_triangles=250000)
    V, C, N, cls, T = supported_mesh(fusion.extract_mesh(), engine.box.size_m, xyz, nframes, mcfg, weak)
    timings["mesh_s"] = time.perf_counter() - t1
    glb_extras = {"frame": "object", "units": "m", "up": "+y", "provenance_classes": {"0": "measured", "1": "interpolated", "2": "estimated"}}
    # The box is rectangular, the dish is not: the bare table caught in the corners is not part of the
    # delivered model. The version with the table is kept beside it; nothing is added or closed.
    dish_info = {"status": "no_mesh"}
    fp = None
    if len(T):
        dish_info = {"status": "nothing_to_remove"}
        try:
            fp = DishFootprint.from_vertices(V) if remove_table else None
            keep_t = fp.keep(V)[T].all(1) if fp is not None else None
            if keep_t is not None and 0 < keep_t.sum() < len(T):
                write_glb(out_dir / "model_avec_table.glb", V, T, N, colors=C, provenance=cls.astype(np.float32), extras=glb_extras)
                removed = int((~keep_t).sum())
                V, C, N, cls, T = crop_mesh(V, C, N, cls, T, keep_t)
                V, C, N, cls, T, crumbs = drop_small_pieces(V, C, N, cls, T)
                kp = fp.keep(xyz)
                xyz, rgb, pcls, nframes, weak = xyz[kp], rgb[kp], pcls[kp], nframes[kp], weak[kp]
                glb_extras = {**glb_extras, "table_removed": True}
                hull = fp.hull_xz()
                (out_dir / "dish_footprint.json").write_text(json.dumps({
                    "frame": "object", "units": "m", "table_y": fp.table_y, "top_y": float(V[:, 1].max()),
                    "hull_xz": hull.tolist()}))
                dish_info = {"status": "ok", "triangles": int(len(T)), "removed_triangles": removed, "crumb_triangles": crumbs, "table_y_m": fp.table_y}
        except Exception as exc:
            dish_info = {"status": "failed", "error": repr(exc)}
    # A finished look: teeth and thin tongues along the outline are trimmed, scraps of the surroundings dropped.
    clean_info = {"status": "disabled"}
    if clean and len(T):
        n0 = len(T)
        kt = trim_ragged_border(T)
        if not kt.all():
            V, C, N, cls, T = crop_mesh(V, C, N, cls, T, kt)
        V, C, N, cls, T, scraps = drop_small_pieces(V, C, N, cls, T, min_area_share=0.02)
        clean_info = {"status": "ok", "outline_triangles_trimmed": int((~kt).sum()), "scrap_triangles": scraps, "triangles_before": n0}
    # Close the surface: a smooth patch across each hole and, when the table was removed, a flat base under the
    # dish. What was reconstructed is kept as it is (also delivered alone, model_mesure.glb); what is added is
    # labelled ESTIMATED. See closure.py.
    closure_info = {"status": "disabled"}
    if close and len(T):
        try:
            write_glb(out_dir / "model_mesure.glb", V, T, N, colors=C, provenance=cls.astype(np.float32), extras=glb_extras)
            on_table = dish_info.get("status") == "ok" and fp is not None
            floor_xz = None
            if on_table:   # the base goes strictly under the dish: the inner part of its footprint, not its outline
                under = fp.core if fp.core is not None and fp.core.any() else fp.grid
                ii, jj = np.nonzero(under)
                floor_xz = (np.stack([ii, jj], 1) + 0.5) * fp.cell_m + fp.origin
            # Where the cameras were: a hole they looked at was photographed, only not measured (uniform or shiny
            # area). Those are closed even when wide, and the photographs are then laid over them like the rest.
            cams = np.array(list(fusion.camera_centres.values()), np.float64).reshape(-1, 3)
            V, C, N, cls, T, closure_info = close_surface(
                V, C, N, cls, T, engine.box.size_m, floor_y=fp.table_y if on_table else None, floor_xz=floor_xz,
                floor_slope=(fp.slope_x, fp.slope_z) if on_table else (0.0, 0.0), cameras=cams if len(cams) else None)
            if closure_info.get("added_triangles"):
                glb_extras = {**glb_extras, "closed": True}
        except Exception as exc:   # never lose a scan because the closing failed: the open model is delivered
            closure_info = {"status": "failed", "error": repr(exc)}
    completion = NoCompletion().propose(V, T, cls, engine.box.size_m)
    write_points_ply(out_dir / "points.ply", xyz, rgb, pcls, nframes)
    write_mesh_ply(out_dir / "mesh.ply", V, C, N, cls, T)
    tex_info = {"status": "not_requested"}
    if len(T):
        if texture:
            emit({"type": "finish_progress", "step": "texture", "done": 0, "total": 1})
            t2 = time.perf_counter()
            try:
                # The delivered file: fewer triangles, texture taken from the photographs at full resolution,
                # vertices shared wherever the atlas has no seam, JPEG texture. The full mesh stays in mesh.ply.
                Vw, Cw, Nw, cw, Tw = decimate_for_web(V, C, N, cls, T, web_triangles)
                Tw = Tw[distinct_triangles(Tw)]        # the atlas refuses two triangles on the same three vertices...
                ok_t = edge_manifold_triangles(Tw)     # ...and an edge shared by three triangles
                if not ok_t.all():
                    Tw = Tw[ok_t]
                views = _texture_views(fin, list(fusion.integrated_frames))
                under = (cw[Tw] == ESTIMATED).all(1) & (Nw[Tw].mean(1)[:, 1] < -0.5)   # the added base, facing down
                tri_uv, tex, nv, filled = texture_mesh(Vw, Tw, views, colors_bgr=Cw[:, ::-1].astype(np.float64), plain=under)
                Vg, Ng, UVg, Pg, Tg = weld_corners(Vw, Nw, cw, Tw, tri_uv)
                write_glb(out_dir / "model.glb", Vg, Tg, Ng, uv=UVg, texture_bgr=tex, provenance=Pg, extras=glb_extras,
                          texture_jpeg_quality=88)
                cv2.imwrite(str(out_dir / "texture.png"), tex)
                tex_info = {"status": "ok", "views": nv, "size": int(tex.shape[0]), "seconds": time.perf_counter() - t2,
                            "filled_from_vertex_colours": filled, "source_width": int(views[0].image.shape[1]) if views else None,
                            "triangles": int(len(Tg)), "vertices": int(len(Vg)),
                            "file_mb": round((out_dir / "model.glb").stat().st_size / 1e6, 2)}
                # The same mesh and texture for iPhone and iPad: opened by iOS itself, in 3D or placed on the table.
                try:
                    uz = write_usdz(out_dir / "model.usdz", Vg, Tg, Ng, UVg, tex, texture_jpeg_quality=88)
                    tex_info["usdz"] = {"status": "ok", "file_mb": round(uz["bytes"] / 1e6, 2)}
                except Exception as exc:      # the GLB is delivered whatever happens here
                    tex_info["usdz"] = {"status": "failed", "error": repr(exc)}
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
        cd = classify_vertices(Vd, xyz, nframes, mcfg, weak)
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
    try:  # a picture of the result, easy to check and to share
        from .preview_format import decode_geometry
        from .render import contact_sheet
        cv2.imwrite(str(out_dir / "apercu.png"), contact_sheet(decode_geometry((out_dir / "final_preview.dpg").read_bytes()), "mesh"))
    except Exception as exc:
        emit({"type": "error", "code": "render_failed", "message": repr(exc)})
    report = {
        "schema": "dishplay.report/1", "engine": ENGINE_VERSION, "finish_width": finish_width,
        "frames_available": available, "frames_used": len(usable), "frames_integrated_final": len(fusion.integrated_frames),
        "closure": closure_info, "cleaning": clean_info, "pairs": pair_stats, "pair_bias": fin.metrics()["pair_bias"], "mono_fill": {**fin.mono_report(), **({"reason": mono_reason} if mono is None and mono_reason else {})}, "points": int(len(xyz)), "confirmed_points": int((pcls == MEASURED).sum()),
        "mesh": {"vertices": int(len(V)), "triangles": int(len(T)), "surface": areas,
                 "provenance_vertices": {"measured": int((cls == MEASURED).sum()), "interpolated": int((cls == INTERPOLATED).sum()),
                                         "estimated": int((cls == ESTIMATED).sum())}},
        "pose_refinement": pose_info, "dish_only": dish_info,
        "completion": {"provider": "none", "applied": completion is not None},
        "texture": tex_info, "footprint_width": fw, "scale_check": scale,
        "live": engine.metrics(), "snapshots": engine.snapshot_log, "timings_s": {**timings, "total": time.perf_counter() - t0},
        "notes": [
            "Global pose refinement (bundle adjustment on SIFT tracks) runs when finishing; it is applied only if it lowers the reprojection error and stays close to ARKit (see pose_refinement).",
            "Gaps are closed with a smooth surface and the dish gets a flat base on the table: gaps up to 16 mm wide everywhere, and wider holes (up to 6 cm) when they are enclosed by the reconstructed surface and the cameras looked at them (photographed, not measured). Everything added is labelled estimated (class 2) and textured from the photographs where they show it; the model as measured is kept in model_mesure.glb (see closure).",
            "model.usdz holds the same mesh and texture as model.glb, for AR Quick Look on iPhone and iPad; it is written only when the texture succeeded.",
        ],
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=float))
    # Poses actually used for the final model (refined when the global refinement was applied): lets other
    # tools (tools/export_splat_dataset.py) start from the best cameras instead of the raw tracker poses.
    (out_dir / "poses.json").write_text(json.dumps({
        "convention": "T_object_from_cameraCV, 4x4 row-major, metres",
        "T_object_from_cameraCV": {str(f): fin._view(f).T_obj_from_cam.reshape(-1).tolist() for f in sorted(fusion.integrated_frames)}}))
    manifest = {"schema": "dishplay.manifest/1", "files": sorted(p.name for p in out_dir.iterdir() if p.is_file() and p.name != "manifest.json"),
                "frame": "object (box): origin centre of box base, +y up, metres", "engine": ENGINE_VERSION,
                "box": {"T_world_from_object": engine.box.T_world_from_object.reshape(-1).tolist(), "size_m": list(engine.box.size_m),
                        "epoch": engine.box.epoch, "revision": engine.box.revision}}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    emit({"type": "finish_progress", "step": "done", "done": 1, "total": 1})
    return report
