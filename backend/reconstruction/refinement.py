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
from .quality import scan_quality
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


def _plain_texels(shape, base: np.ndarray, pts: np.ndarray, plain: np.ndarray) -> np.ndarray:
    """The texels of the triangles marked `plain`, with the texel border of each triangle."""
    mask = np.zeros(shape, np.uint8)
    for k in np.nonzero(plain)[0]:
        cv2.fillConvexPoly(mask, pts[k], 255, lineType=cv2.LINE_8, shift=2)
    return (cv2.dilate(mask, np.ones((3, 3), np.uint8)) > 0) & (base.sum(2) > 0)


def _paint_plain(tex: np.ndarray, base: np.ndarray, pts: np.ndarray, plain: np.ndarray) -> int:
    """Give the triangles marked `plain` their plain surface colour (taken from `base`) in the atlas, whatever
    the photographs projected there. Returns the number of texels repainted."""
    sel = _plain_texels(tex.shape[:2], base, pts, plain)
    tex[sel] = base[sel]
    return int(sel.sum())


def _projected_share(tm, views, Ks, Es, tex_size: int) -> np.ndarray:
    """Per texel, between 0 and 1: how much of its colour the projection really took from the photographs.

    Open3D blends the photographs that reach a texel, but where the surface turns away from the cameras the
    blend comes out darker than every photograph (measured on a ball under 16 plain grey-200 pictures: grey 35
    to 130 on the flank that faces down). The blend is linear in the pictures (checked to one grey level), so
    projecting all-white pictures through the same cameras gives the factor that was applied to each texel."""
    white = {}
    for v in views:
        size = v.image.shape[:2]
        if size not in white:
            white[size] = o3d.t.geometry.Image(np.full((size[0], size[1], 3), 255, np.uint8))
    out = tm.project_images_to_albedo([white[v.image.shape[:2]] for v in views], Ks, Es, tex_size, False)
    return np.asarray(out.as_tensor().numpy())[:, :, :3].max(2).astype(np.float32) / 255.0


def texture_mesh(V, T, views, tex_size: int = 2048, max_views: int = 36, colors_bgr: np.ndarray | None = None,
                 plain: np.ndarray | None = None, min_share: float = 0.2):
    """UV atlas + projection of calibrated images (Open3D).

    min_share: below this share of real photograph (see _projected_share) a texel takes the fused colour.

    Returns (per-corner uv in glTF convention, texture BGR, views used, fraction filled from vertex colours:
    the share of the surface the photographs could have shown and did not, the `plain` triangles left out)."""
    tm = o3d.t.geometry.TriangleMesh()
    tm.vertex.positions = o3d.core.Tensor(V.astype(np.float32))
    tm.triangle.indices = o3d.core.Tensor(T.astype(np.int32))
    tm.compute_uvatlas(size=tex_size)
    sel = views
    if len(views) > max_views:
        sel = [views[i] for i in texture_view_choice(np.stack([v.T_obj_from_cam[:3, 3] for v in views]), max_views)]
    imgs = [o3d.t.geometry.Image(np.ascontiguousarray(v.image[:, :, ::-1])) for v in sel]
    Ks = [o3d.core.Tensor(v.K.astype(np.float64)) for v in sel]
    Es = [o3d.core.Tensor(invert_rigid(v.T_obj_from_cam).astype(np.float64)) for v in sel]
    albedo = tm.project_images_to_albedo(imgs, Ks, Es, tex_size, True)
    tex = np.asarray(albedo.as_tensor().numpy())
    tex = tex[:, :, ::-1].copy() if tex.shape[2] == 3 else cv2.cvtColor(tex, cv2.COLOR_RGBA2BGR)
    # Each texel back to the brightness of the photographs: divided by the share of them it received. Under
    # min_share too little of a photograph is left to be trusted (and dividing would only amplify its rounding).
    share = _projected_share(tm, sel, Ks, Es, tex_size)
    tex = np.clip(np.rint(tex.astype(np.float32) / np.maximum(share, min_share)[:, :, None]), 0, 255).astype(np.uint8)
    tri_uv = tm.triangle["texture_uvs"].numpy().astype(np.float64)  # (M, 3, 2) per corner, v pointing UP (Open3D)
    h, w = tex.shape[:2]
    # Texels that the selected images did not reach, or hardly, are black or dark in Open3D's result. Fill them
    # with the fused colour of their triangle (measured vertex colours), so the model has no dark patches.
    base = np.zeros_like(tex)
    px = np.stack([tri_uv[:, :, 0] * (w - 1), (1.0 - tri_uv[:, :, 1]) * (h - 1)], -1)
    tri_col = colors_bgr[T].mean(1) if colors_bgr is not None else None
    filled = 0.0
    if tri_col is not None:
        pts = np.round(px * 4).astype(np.int32)
        for k in range(len(pts)):
            cv2.fillConvexPoly(base, pts[k], tri_col[k].tolist(), lineType=cv2.LINE_8, shift=2)
        unprojected = (share < min_share) & (base.sum(2) > 0)
        counted = base.sum(2) > 0
        tex[unprojected] = base[unprojected]
        if plain is not None and plain.any():
            # The base under the dish faces the table: no photograph shows it, and what the projection puts
            # there comes from views that grazed it through a gap (grey streaks on a real capture). It is
            # painted plain, and it does not count in the share below: no photograph could have shown it.
            counted &= ~_plain_texels(tex.shape[:2], base, pts, plain)
            _paint_plain(tex, base, pts, plain)
        filled = float(unprojected[counted].mean()) if counted.any() else 0.0
    # glTF texture coordinates have their origin at the TOP-left of the image: flip v.
    uv = tri_uv.copy()
    uv[:, :, 1] = 1.0 - uv[:, :, 1]
    return uv, tex, len(sel), filled


def spread_views(centres: np.ndarray, count: int, sharpness: np.ndarray | None = None) -> list[int]:
    """Indices of at most `count` cameras spread as evenly as possible over the positions `centres` (Nx3).

    The cameras are picked one by one, each time the one farthest from those already chosen: every part of the
    path is represented, whatever the order of capture. With `sharpness` (one number per camera, higher is
    sharper), each chosen camera then gives its place to the sharpest camera of its own neighbourhood - the
    cameras that are closer to it than to any other chosen one, which show the same thing."""
    n = len(centres)
    if count <= 0 or n <= count:
        return list(range(n))
    C = np.asarray(centres, np.float64)
    chosen = [0]
    d = np.linalg.norm(C - C[0], axis=1)
    for _ in range(count - 1):
        k = int(np.argmax(d))
        chosen.append(k)
        d = np.minimum(d, np.linalg.norm(C - C[k], axis=1))
    if sharpness is not None:
        sharp = np.asarray(sharpness, np.float64)
        owner = np.argmin(np.linalg.norm(C[:, None, :] - C[chosen][None, :, :], axis=2), axis=1)
        for j, seed in enumerate(chosen):
            members = np.nonzero(owner == j)[0]
            best = int(members[np.argmax(sharp[members])]) if len(members) else seed
            if sharp[best] > sharp[seed]:
                chosen[j] = best
    return sorted(set(chosen))


def texture_view_choice(centres: np.ndarray, count: int, sharpness: np.ndarray | None = None, tour_band_deg: float = 10.0) -> list[int]:
    """Indices of the cameras whose photographs paint the texture, `count` at most, for cameras at `centres`
    (Nx3, object frame: the vertical axis of the box in the middle, +y up).

    One camera per direction around the dish - `count` equal sectors of azimuth - taken from the MAIN TOUR:
    the height at which the scan has the most cameras, give or take `tour_band_deg`. In each sector the
    sharpest camera of the tour wins (`sharpness`: one number per camera, higher is sharper), the one nearest
    the middle of the sector among equals. A sector the tour did not visit takes its camera nearest to that
    height. Places still free go to the cameras farthest from those chosen: another pass covers what the tour
    did not show.

    Two simpler rules were measured and dropped. The first photographs in capture order (the rule until
    p1-0.10.0): a tour of 37 to 107 views lost its end, up to half of it, and that side of the dish got no
    photograph at all. Cameras spread over the whole scan, both heights mixed: on the hand-held bench (one lap
    and a higher partial lap) the colour error of the delivered texture rose (mean 11.8 -> 12.9 of 255, 90th
    percentile 25 -> 30), most on the surfaces that face up: a photograph taken from another height than the
    views that measured a surface lands beside its place wherever that surface is a millimetre off."""
    n = len(centres)
    if count <= 0 or n <= count:
        return list(range(n))
    C = np.asarray(centres, np.float64)
    azimuth = np.arctan2(C[:, 2], C[:, 0])
    height = np.degrees(np.arctan2(C[:, 1], np.hypot(C[:, 0], C[:, 2])))
    # The main tour: the height with the most cameras around it (the lower one when two tours are equal: it
    # is the one that sees the flanks).
    near = (np.abs(height[:, None] - height[None, :]) <= tour_band_deg).sum(1)
    tour = float(height[np.lexsort((height, -near))[0]])
    sector = np.floor((azimuth + np.pi) / (2 * np.pi) * count).astype(int) % count
    sharp = None if sharpness is None else np.asarray(sharpness, np.float64)
    chosen = []
    for k in range(count):
        members = np.nonzero(sector == k)[0]
        if not len(members):
            continue
        off = np.abs(height[members] - tour)
        on_tour = members[off <= tour_band_deg]
        if not len(on_tour):
            chosen.append(int(members[np.argmin(off)]))
            continue
        if sharp is not None:
            on_tour = on_tour[sharp[on_tour] >= 0.9 * sharp[on_tour].max()]
        middle = -np.pi + (k + 0.5) * 2 * np.pi / count
        chosen.append(int(on_tour[np.argmin(np.abs(np.angle(np.exp(1j * (azimuth[on_tour] - middle)))))]))
    if len(chosen) < count:
        d = np.linalg.norm(C[:, None, :] - C[chosen][None, :, :], axis=2).min(1) if chosen else np.full(n, np.inf)
        while len(chosen) < count:
            k = int(np.argmax(d))
            if d[k] <= 0:
                break
            chosen.append(k)
            d = np.minimum(d, np.linalg.norm(C - C[k], axis=1))
    return sorted(set(chosen))


def _texture_views(fin: SessionEngine, frame_ids: list[int], max_views: int = 36) -> list[View]:
    """The views that paint the texture, at the resolution of the stored photographs (the depth was computed
    on reduced images; the texture need not be). One per direction around the dish, from the main tour, the
    sharpest of each place (see texture_view_choice): the first photographs in capture order used to be taken,
    which left the end of a tour (up to half of it) out of the texture."""
    if not frame_ids:
        return []
    centres = np.stack([fin._geometry(f)[0][:3, 3] for f in frame_ids])
    sharpness = np.array([fin.frames[f].sharpness for f in frame_ids])
    out = []
    for f in (frame_ids[i] for i in texture_view_choice(centres, max_views, sharpness)):
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
    return [frame_ids[i] for i in spread_views(C, max_frames)]


def final_fallbacks(tex_info: dict, dish_info: dict, closure_info: dict, pose_info: dict, mono_reason: str,
                    used: int, integrated: int) -> list[dict]:
    """What the final step could not do as intended, each as {"code", "message"}: a stable code and one French
    sentence for the person who scanned. These used to be written in report.json only, which nobody reads: a
    model with approximate colours or with its table left around it was announced exactly like a good one.
    Normal operation is not listed: a pose refinement that was not needed, a dish with no table to remove, a
    depth model turned off on purpose."""
    out = []

    def say(code: str, message: str):
        out.append({"code": code, "message": message})

    status = tex_info.get("status")
    if status == "failed_fallback_vertex_colors":
        say("texture_failed", "Les photos n'ont pas pu être posées sur le modèle : ses couleurs sont approximatives.")
    elif status == "ok" and (tex_info.get("filled_from_vertex_colours") or 0.0) > 0.25:
        share = int(round(100 * tex_info["filled_from_vertex_colours"]))
        say("texture_partly_missing", f"Environ {share} % de la surface visible n'a été bien vue par aucune photo : ses couleurs y sont approximatives.")
    if status == "failed_fallback_vertex_colors" or (status == "ok" and tex_info.get("usdz", {}).get("status") != "ok"):
        say("ar_file_missing", "Le fichier qui sert à voir le plat sur la table n'a pas pu être écrit.")
    if dish_info.get("status") == "failed":
        say("table_not_removed", "La table autour du plat n'a pas pu être retirée du modèle.")
    if closure_info.get("status") == "failed":
        say("holes_not_closed", "Les trous du modèle n'ont pas pu être refermés.")
    if pose_info.get("reason") == "error":
        say("poses_not_refined", "Les positions du téléphone n'ont pas pu être affinées : le modèle peut être un peu moins net.")
    if mono_reason.startswith(("model_not_found", "onnxruntime_not_installed", "load_failed")):
        say("depth_model_missing", "Le modèle de profondeur n'est pas disponible sur le PC : les surfaces unies ou brillantes peuvent être moins bien reconstruites.")
    if used and integrated < max(8, 0.5 * used):
        say("few_views_used", f"Seules {integrated} vues sur {used} ont pu être utilisées : le modèle est moins complet.")
    return out


def finish_session(engine: SessionEngine, out_dir: Path, finish_width: int = 1152, reference_width_m: float | None = None,
                   texture: bool = True, emit: Callable[[dict], None] | None = None, refine: bool = True,
                   remove_table: bool = True, max_frames: int = 140, mono=None, mono_reason: str = "",
                   close: bool = True, clean: bool = True, web_triangles: int = 60000, texture_size: int = 2048) -> dict:
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
    as_measured = (V, T, cls)     # the dish as reconstructed, before anything is added: what the verdict judges
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
                tri_uv, tex, nv, filled = texture_mesh(Vw, Tw, views, tex_size=texture_size, colors_bgr=Cw[:, ::-1].astype(np.float64),
                                                       plain=under)
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
    # How good is this scan? The verdict given during the scan (quality.py), computed the same way on the same
    # kind of surface: the dish as the final calculation reconstructed it, before the gaps are closed and the
    # base is added (those are estimates; they make the model whole, they say nothing about the scan). A final
    # model is never "too early": too little to judge is poor.
    sides = float((np.array(fin.coverage()["views_per_bin"]).sum(0) > 0).mean())
    Vq, Tq, clsq = as_measured
    verdict = scan_quality(Vq, Tq, clsq, fp if dish_info.get("status") == "ok" else None, len(fusion.integrated_frames), sides,
                           engine.box.size_m)
    if verdict["level"] == "too_early":
        verdict = {**verdict, "level": "poor"}
    verdict = json.loads(json.dumps(verdict, default=float))      # plain numbers: it travels in events and files
    fallbacks = final_fallbacks(tex_info, dish_info, closure_info, pose_info, mono_reason if mono is None else "",
                                len(usable), len(fusion.integrated_frames))
    sel = slice(None) if len(xyz) <= 150000 else np.linspace(0, len(xyz) - 1, 150000).astype(np.int64)
    header = {"schema": "dishplay.geometry/1", "engine": ENGINE_VERSION, "version": 1_000_000 + engine.version, "kind": "final",
              "frame": "object", "units": "m", "box_revision": engine.box.revision, "epoch": engine.box.epoch,
              "box_size_m": list(engine.box.size_m), "computed_at": time.time(), "last_frame_ids": fusion.integrated_frames[-5:],
              "integrated_frames": len(fusion.integrated_frames), "received_frames": len(engine.frames),
              "measured_points": int(len(xyz)), "confirmed_points": int((pcls == MEASURED).sum()), "surface": areas,
              "coverage": fin.coverage(), "quality": verdict}
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
        "verdict": verdict, "fallbacks": fallbacks,
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
