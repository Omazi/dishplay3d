"""Reconstruction worker: a separate PROCESS so HTTP/WebSocket stay responsive."""
from __future__ import annotations

import errno
import json
import multiprocessing
import os
import queue
import signal
import sqlite3
import time
import traceback
from pathlib import Path

# Why a final calculation ended without a model: one sentence for the person, shown in the app and on the PC.
FAILURE_TEXT = {
    "exception": "Le calcul du modèle a échoué sur le PC ; vous pouvez le relancer (détails dans calculateur.log).",
    "disk_full": "Le disque du PC est plein : libérez de la place, puis relancez le calcul.",
    "memory": "Le PC a manqué de mémoire pendant le calcul : fermez d'autres programmes, puis relancez-le.",
    "no_model": "Aucune vue utilisable dans ce scan : refaites le scan du plat.",
    "died": "Le calcul s'est arrêté brutalement sur le PC, peut-être par manque de mémoire ; vous pouvez le relancer.",
    "interrupted_twice": "Le calcul a été interrompu deux fois par l'arrêt du calculateur ; relancez-le quand le PC peut rester allumé.",
    "start": "Le calcul n'a pas pu démarrer sur le PC (détails dans calculateur.log).",
}


def failure_reason(exc: BaseException) -> str:
    """Which sentence of FAILURE_TEXT fits this exception."""
    if isinstance(exc, MemoryError) or "Insufficient memory" in str(exc):
        return "memory"
    if isinstance(exc, OSError) and (exc.errno in (errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC))
                                     or getattr(exc, "winerror", None) in (39, 112)):
        return "disk_full"
    if isinstance(exc, sqlite3.OperationalError) and "full" in str(exc).lower():     # "database or disk is full"
        return "disk_full"
    return "exception"


class CalculatorGone(BaseException):
    """The calculator that started this process is gone (killed, not closed): nobody listens any more. Not an
    Exception, so that no `except Exception` on the way keeps the calculation going."""


def worker_main(cmd_q, evt_q, session_dir: str, box_json: dict, settings: dict, existing_frames: list):
    try:
        _work(cmd_q, evt_q, session_dir, box_json, settings, existing_frames)
    except CalculatorGone:
        pass    # stop without a word: there is nobody left to tell


def _work(cmd_q, evt_q, session_dir: str, box_json: dict, settings: dict, existing_frames: list):
    calculator = multiprocessing.parent_process()     # None when the worker is run inside a test
    if calculator is not None:
        # Ctrl+C in the calculator's terminal reaches every process of that terminal. The calculator decides
        # when this one stops, and takes an interrupted final calculation up again at its next start.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    # Imports inside the child process (spawn on Windows/macOS).
    from reconstruction.engine import Box, EngineConfig, SessionEngine
    from reconstruction.refinement import finish_session

    sdir = Path(session_dir)
    sid = sdir.name

    def emit(ev):
        if calculator is not None and not calculator.is_alive():
            # A calculator that was killed leaves this process behind, and gives the dish to a new process
            # when it starts again: this one must not go on writing in the same folder. Everything long says
            # something from time to time (progress, views), so this is noticed within a step.
            raise CalculatorGone()
        ev.setdefault("session_id", sid)
        evt_q.put(ev)

    cfg = EngineConfig()
    cfg.use_lidar = bool(settings.get("use_lidar", False))
    if "preview_width" in settings:
        cfg.preview_width = int(settings["preview_width"])
    engine = SessionEngine(sdir, Box.from_json(box_json), cfg, emit=emit)
    # Learned depth for uniform or shiny surfaces (reconstruction/mono_depth.py). It runs on a thread of its
    # own, at the same time as stereo, during the scan and when finishing. During the scan it never makes a
    # view wait: a prediction that is not ready is not used, and a computer that cannot keep up makes the model
    # step back by itself until the finishing step (AsyncMono). DISHPLAY_MONO=0 turns the model off,
    # DISHPLAY_MONO_LIVE=0 keeps it for the finishing step only.
    mono_state = {"model": None, "reason": "not_loaded"}

    def mono_model():
        if not settings.get("mono", True) or os.environ.get("DISHPLAY_MONO", "1") == "0":
            mono_state["reason"] = "disabled"
            return None
        if mono_state["model"] is None and mono_state["reason"] == "not_loaded":
            from reconstruction.mono_depth import AsyncMono, load_default
            model, mono_state["reason"] = load_default(sdir)
            mono_state["model"] = AsyncMono(model) if model is not None else None
        return mono_state["model"]

    if settings.get("mono_live", True) and os.environ.get("DISHPLAY_MONO_LIVE", "1") != "0":
        engine.mono = mono_model()
    for meta_path, received_at in existing_frames:  # resume after a server restart
        _add(engine, Path(meta_path), received_at)
    paused = False
    last_activity = time.time()
    emit({"type": "status", "state": "capturing", "queue": len(engine.pending())})
    while True:
        if calculator is not None and not calculator.is_alive():
            return      # the calculator was killed: no "stop" will ever come
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
                    # The server waits for "finish_over" before it gives the calculator to the next dish: it is
                    # sent whatever happens, after the optional neural step. It never goes to the phones.
                    over = {"type": "finish_over", "ok": False}
                    try:
                        emit({"type": "status", "state": "finishing", "queue": len(engine.pending())})
                        engine.process_pending(live=False)
                        engine.flush()
                        snap = engine.snapshot()
                        if snap:
                            _publish(sdir, *snap, emit)
                        rep = finish_session(engine, sdir / "final", reference_width_m=cmd[1], emit=emit,
                                             texture=bool(settings.get("texture", True)),
                                             mono=mono_model(), mono_reason=mono_state["reason"])
                        if not (sdir / "final" / "model.glb").exists() or not (rep.get("mesh") or {}).get("triangles"):
                            # The engine ran to its end with nothing to build (no usable view, for example):
                            # that is a failure, not a model that is ready.
                            over["reason"] = "no_model"
                            emit({"type": "error", "code": "no_model", "message": FAILURE_TEXT["no_model"]})
                        else:
                            files = sorted(p.name for p in (sdir / "final").iterdir() if p.is_file())
                            emit({"type": "geometry", "url": f"/sessions/{sid}/artifacts/final_preview.dpg",
                                  "header": {"version": 1_000_000 + engine.version, "kind": "final"}})
                            report = {k: rep.get(k) for k in ("mesh", "texture", "scale_check", "footprint_width", "timings_s")}
                            report.update({k: rep[k] for k in ("verdict", "fallbacks") if k in rep})   # how good, and what fell back
                            emit({"type": "artifacts", "files": files, "report": report})
                            emit({"type": "status", "state": "done", "queue": 0})
                            over["ok"] = True
                    except Exception as exc:
                        trace = traceback.format_exc()
                        over.update(reason=failure_reason(exc), detail=repr(exc), trace=trace[-6000:])
                        # The published app shows `message` to the person: a sentence; the Python error is in `detail`.
                        emit({"type": "error", "code": "worker_exception", "message": FAILURE_TEXT[over["reason"]],
                              "detail": repr(exc), "trace": trace[-2000:]})
                    # Optional neural model, after the classic one has been delivered. Only on a machine with
                    # an NVIDIA GPU, PyTorch and gsplat; a failure here never affects the classic result.
                    if over["ok"] and settings.get("neural", True):
                        try:
                            from reconstruction.neural import neural_available, run_neural
                            ok, why = neural_available()
                            if ok:
                                nrep = run_neural(sdir, sdir / "final", emit, steps=int(settings.get("neural_steps", 7000)))
                                emit({"type": "artifacts", "files": sorted(p.name for p in (sdir / "final").iterdir() if p.is_file()),
                                      "neural": {k: nrep.get(k) for k in ("heldout_psnr_db", "gaussians", "total_seconds", "files")}})
                        except Exception as exc:
                            emit({"type": "error", "code": "neural_failed", "message": repr(exc), "trace": traceback.format_exc()[-2000:]})
                    emit(over)
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
