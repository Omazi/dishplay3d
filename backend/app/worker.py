"""Reconstruction worker: a separate PROCESS so HTTP/WebSocket stay responsive."""
from __future__ import annotations

import json
import os
import queue
import time
import traceback
from pathlib import Path


def worker_main(cmd_q, evt_q, session_dir: str, box_json: dict, settings: dict, existing_frames: list):
    # Imports inside the child process (spawn on Windows/macOS).
    from reconstruction.engine import Box, EngineConfig, SessionEngine
    from reconstruction.refinement import finish_session

    sdir = Path(session_dir)
    sid = sdir.name

    def emit(ev):
        ev.setdefault("session_id", sid)
        evt_q.put(ev)

    cfg = EngineConfig()
    cfg.use_lidar = bool(settings.get("use_lidar", False))
    if "preview_width" in settings:
        cfg.preview_width = int(settings["preview_width"])
    engine = SessionEngine(sdir, Box.from_json(box_json), cfg, emit=emit)
    # Learned depth for uniform or shiny surfaces (reconstruction/mono_depth.py). Used when finishing;
    # during capture only on request, because it adds processor time to every view.
    mono_state = {"model": None, "reason": "not_loaded"}

    def mono_model():
        if not settings.get("mono", True) or os.environ.get("DISHPLAY_MONO", "1") == "0":
            mono_state["reason"] = "disabled"
            return None
        if mono_state["model"] is None and mono_state["reason"] == "not_loaded":
            from reconstruction.mono_depth import load_default
            mono_state["model"], mono_state["reason"] = load_default(sdir)
        return mono_state["model"]

    if settings.get("mono_live", False):
        engine.mono = mono_model()
    for meta_path, received_at in existing_frames:  # resume after a server restart
        _add(engine, Path(meta_path), received_at)
    paused = False
    last_activity = time.time()
    emit({"type": "status", "state": "capturing", "queue": len(engine.pending())})
    while True:
        cmds = []
        try:
            cmds.append(cmd_q.get(timeout=0.2))
            while True:
                cmds.append(cmd_q.get_nowait())
        except queue.Empty:
            pass
        for cmd in cmds:
            kind = cmd[0]
            try:
                if kind == "frame":
                    _add(engine, Path(cmd[1]), cmd[2])
                elif kind == "pause":
                    paused = True
                    emit({"type": "status", "state": "paused", "queue": len(engine.pending())})
                elif kind == "resume":
                    paused = False
                    emit({"type": "status", "state": "capturing", "queue": len(engine.pending())})
                elif kind == "box":
                    engine.set_box(Box.from_json(cmd[1]), reprocess=True)
                elif kind == "finish":
                    emit({"type": "status", "state": "finishing", "queue": len(engine.pending())})
                    engine.process_pending(live=False)
                    engine.flush()
                    snap = engine.snapshot()
                    if snap:
                        _publish(sdir, *snap, emit)
                    rep = finish_session(engine, sdir / "final", reference_width_m=cmd[1], emit=emit,
                                         texture=bool(settings.get("texture", True)),
                                         mono=mono_model(), mono_reason=mono_state["reason"])
                    files = sorted(p.name for p in (sdir / "final").iterdir() if p.is_file())
                    emit({"type": "geometry", "url": f"/sessions/{sid}/artifacts/final_preview.dpg",
                          "header": {"version": 1_000_000 + engine.version, "kind": "final"}})
                    emit({"type": "artifacts", "files": files, "report": {k: rep[k] for k in ("mesh", "texture", "scale_check", "footprint_width", "timings_s")}})
                    emit({"type": "status", "state": "done", "queue": 0})
                    # Optional neural model, after the classic one has been delivered. Only on a machine with
                    # an NVIDIA GPU, PyTorch and gsplat; a failure here never affects the classic result.
                    if settings.get("neural", True):
                        from reconstruction.neural import neural_available, run_neural
                        ok, why = neural_available()
                        if ok:
                            try:
                                nrep = run_neural(sdir, sdir / "final", emit, steps=int(settings.get("neural_steps", 7000)))
                                emit({"type": "artifacts", "files": sorted(p.name for p in (sdir / "final").iterdir() if p.is_file()),
                                      "neural": {k: nrep.get(k) for k in ("heldout_psnr_db", "gaussians", "total_seconds", "files")}})
                            except Exception as exc:
                                emit({"type": "error", "code": "neural_failed", "message": repr(exc), "trace": traceback.format_exc()[-2000:]})
                elif kind == "stop":
                    return
            except Exception as exc:  # never die silently: report and continue
                emit({"type": "error", "code": "worker_exception", "message": repr(exc), "trace": traceback.format_exc()[-2000:]})
        if cmds and any(c[0] == "stop" for c in cmds):
            return
        try:
            n = engine.process_pending(live=True)
            if cmds:
                last_activity = time.time()
            elif engine.awaiting_confirmation() and time.time() - last_activity > 1.5:
                n += engine.flush()  # capture stopped or paused: fuse the last views with what is available
            if engine.should_snapshot():
                snap = engine.snapshot()
                if snap:
                    _publish(sdir, *snap, emit)
            if n:
                emit({"type": "status", "state": "paused" if paused else "capturing", "queue": len(engine.pending()),
                      "metrics": engine.metrics()})
        except Exception as exc:
            emit({"type": "error", "code": "worker_exception", "message": repr(exc), "trace": traceback.format_exc()[-2000:]})
            time.sleep(0.5)


def _add(engine, meta_path: Path, received_at: float):
    meta = json.loads(meta_path.read_text())
    base = meta_path.with_suffix("")
    depth = base.with_suffix(".depth") if base.with_suffix(".depth").exists() else None
    conf = base.with_suffix(".conf") if base.with_suffix(".conf").exists() else None
    engine.add_frame(meta, base.with_suffix(".jpg"), depth, conf, received_at)


def _publish(sdir: Path, header: dict, blob: bytes, emit):
    pdir = sdir / "preview"
    pdir.mkdir(exist_ok=True)
    name = f"v{header['version']:05d}.dpg"
    tmp = pdir / (name + ".tmp")
    tmp.write_bytes(blob)
    tmp.replace(pdir / name)
    (pdir / "latest.json").write_text(json.dumps({"version": header["version"], "file": name}))
    emit({"type": "geometry", "url": f"/sessions/{sdir.name}/preview/{header['version']}", "header": header, "bytes": len(blob)})
