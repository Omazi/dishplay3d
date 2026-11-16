#!/usr/bin/env python3
"""Replay a captured session deterministically.

  # In-process (no network): re-run the engine on a stored session folder
  python tools/replay_session.py local  <data>/sessions/<id>  --out replay_out [--finish]

  # Over the network: act as the phone and stream the stored frames to a calculator
  python tools/replay_session.py stream <data>/sessions/<id> --url https://192.168.1.20:8765 --fp <sha256> --code 123456

Every intermediate preview is written (v00001.dpg ...) with a metrics JSON so
two engine versions can be compared on exactly the same data.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))


def load_session(sdir: Path):
    sj = json.loads((sdir / "session.json").read_text())
    frames = sorted((sdir / "frames").glob("*.json"))
    return sj, frames


def replay_local(sdir: Path, out: Path, finish: bool, reference_width_m=None, preview_width=640):
    from reconstruction.engine import Box, EngineConfig, SessionEngine
    out.mkdir(parents=True, exist_ok=True)
    sj, frames = load_session(sdir)
    cfg = EngineConfig(preview_width=preview_width)
    cfg.use_lidar = bool(sj.get("settings", {}).get("use_lidar", False))
    clock = {"t": 0.0}
    eng = SessionEngine(sdir, Box.from_json(sj["box"]), cfg, clock=lambda: clock["t"])
    timeline = []
    t0 = time.perf_counter()
    for mp in frames:
        meta = json.loads(mp.read_text())
        base = mp.with_suffix("")
        d = base.with_suffix(".depth")
        c = base.with_suffix(".conf")
        clock["t"] = float(meta["timestamp_s"])  # deterministic: capture timeline drives snapshot cadence
        eng.add_frame(meta, base.with_suffix(".jpg"), d if d.exists() else None, c if c.exists() else None, clock["t"])
        tp = time.perf_counter()
        eng.process_pending(live=False)
        if eng.should_snapshot():
            h, blob = eng.snapshot()
            (out / f"v{h['version']:05d}.dpg").write_bytes(blob)
            timeline.append({"after_frame": meta["frame_id"], "version": h["version"], "kind": h["kind"],
                             "integrated": h["integrated_frames"], "points": h["measured_points"],
                             "triangles": h["triangle_count"] if "triangle_count" in h else None,
                             "process_s": time.perf_counter() - tp})
    eng.flush()
    snap = eng.snapshot()
    if snap:
        (out / f"v{snap[0]['version']:05d}.dpg").write_bytes(snap[1])
    result = {"session": sdir.name, "frames": len(frames), "wall_s": time.perf_counter() - t0,
              "metrics": eng.metrics(), "timeline": timeline}
    if finish:
        from reconstruction.refinement import finish_session
        result["final"] = finish_session(eng, out / "final", reference_width_m=reference_width_m or sj.get("reference_width_m"))
    (out / "replay.json").write_text(json.dumps(result, indent=1, default=float))
    return result


def stream(sdir: Path, url: str, fp: str | None, code: str, finish: bool, realtime: bool):
    from scan_client import EventListener, ScanClient
    sj, frames = load_session(sdir)
    cl = ScanClient(url, fp)
    cl.pair(code, "replay")
    sid = cl.create_session(sj["box"], {**sj.get("device", {}), "platform": "replay", "model": "replay"}, sj.get("reference_width_m"))
    lis = EventListener(url, sid, cl.token, fp)
    lis.start()
    lis.connected.wait(10)
    prev_t = None
    for mp in frames:
        meta = json.loads(mp.read_text())
        if realtime and prev_t is not None:
            time.sleep(max(0.0, min(2.0, meta["timestamp_s"] - prev_t)))
        prev_t = meta["timestamp_s"]
        base = mp.with_suffix("")
        d, c = base.with_suffix(".depth"), base.with_suffix(".conf")
        cl.put_frame(sid, meta, base.with_suffix(".jpg").read_bytes(), d.read_bytes() if d.exists() else b"", c.read_bytes() if c.exists() else b"")
    print("frames sent:", len(frames), "geometry events so far:", len(lis.of("geometry")))
    if finish:
        cl.post(f"/sessions/{sid}/finish")
        t0 = time.time()
        while not lis.of("artifacts") and time.time() - t0 < 1800:
            time.sleep(1)
    lis.stop_flag.set()
    return sid, lis.events


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("local")
    a.add_argument("session_dir")
    a.add_argument("--out", default="replay_out")
    a.add_argument("--finish", action="store_true")
    a.add_argument("--reference-width-m", type=float)
    a.add_argument("--preview-width", type=int, default=640)
    b = sub.add_parser("stream")
    b.add_argument("session_dir")
    b.add_argument("--url", required=True)
    b.add_argument("--fp")
    b.add_argument("--code", required=True)
    b.add_argument("--finish", action="store_true")
    b.add_argument("--realtime", action="store_true")
    args = ap.parse_args()
    if args.cmd == "local":
        r = replay_local(Path(args.session_dir), Path(args.out), args.finish, args.reference_width_m, args.preview_width)
        print(json.dumps({k: r[k] for k in ("frames", "wall_s", "metrics")}, indent=1, default=float))
    else:
        sid, evs = stream(Path(args.session_dir), args.url, args.fp, args.code, args.finish, args.realtime)
        print("session", sid, "events", len(evs))


if __name__ == "__main__":
    main()
