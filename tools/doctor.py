#!/usr/bin/env python3
"""Diagnostic of the calculator machine and network path to the iPhone.

  python tools/doctor.py            full check (includes a short synthetic self-test of the reconstruction chain)
  python tools/doctor.py --quick    versions, memory, addresses, port
The synthetic self-test only proves the libraries work on this machine; it is
never shown as a scan result.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    from app.diagnostics import capabilities
    from app.main import lan_addresses
    rep = {"capabilities": capabilities(str(Path.home())), "lan_addresses": lan_addresses(), "checks": []}

    def check(name, ok, detail=""):
        rep["checks"].append({"name": name, "ok": bool(ok), "detail": detail})

    c = rep["capabilities"]
    check("python>=3.10", sys.version_info >= (3, 10), c["python"])
    check("opencv with SIFT", c.get("opencv_sift"), c.get("opencv", c.get("opencv_error")))
    check("open3d", "open3d" in c, c.get("open3d", c.get("open3d_error")))
    ram = c.get("ram_bytes") or 0
    check("RAM >= 8 GB (4 GB minimum)", ram >= 3.5e9, f"{ram / 1e9:.1f} GB")
    check("LAN address found", bool(rep["lan_addresses"]), ", ".join(rep["lan_addresses"]) or "none: connect to Wi-Fi/Ethernet")
    if c.get("wsl"):
        check("WSL2 networking", False, "WSL2 NAT hides the server from the iPhone: run natively on Windows (start-calculator.ps1) "
                                         "or enable networkingMode=mirrored in %UserProfile%\\.wslconfig")
    s = socket.socket()
    try:
        s.bind(("0.0.0.0", a.port))
        check(f"port {a.port} free", True)
    except OSError:
        check(f"port {a.port} free", False, "already in use (calculator already running?)")
    finally:
        s.close()
    if not a.quick:
        t0 = time.perf_counter()
        try:
            import tempfile
            sys.path.insert(0, str(ROOT / "backend"))
            from reconstruction.engine import Box, SessionEngine
            from tests.helpers import write_session
            with tempfile.TemporaryDirectory() as td:
                from tests.synthetic import orbit_poses
                sdir = write_session(Path(td), poses=orbit_poses(60)[:12])
                sj = json.loads((sdir / "session.json").read_text())
                eng = SessionEngine(sdir, Box.from_json(sj["box"]))
                per = []
                for mp in sorted((sdir / "frames").glob("*.json")):
                    eng.add_frame(json.loads(mp.read_text()), mp.with_suffix(".jpg"))
                    t1 = time.perf_counter()
                    eng.process_pending(live=False)
                    per.append(time.perf_counter() - t1)
                h, _ = eng.snapshot()
            check("reconstruction self-test (synthetic, not a scan)", h["triangle_count"] > 0,
                  f"{h['integrated_frames']} frames, {h['triangle_count']} triangles, {1000 * sorted(per)[len(per) // 2]:.0f} ms/frame median, "
                  f"{time.perf_counter() - t0:.1f} s total")
        except Exception as exc:
            check("reconstruction self-test", False, repr(exc))
    if a.json:
        print(json.dumps(rep, indent=1))
    else:
        print("DishPlay Scan doctor")
        for k in ("python", "platform", "cpu_count", "opencv", "open3d", "open3d_cuda", "nvidia_smi"):
            print(f"  {k}: {c.get(k)}")
        for ch in rep["checks"]:
            print(f"  [{'OK ' if ch['ok'] else 'NO '}] {ch['name']}: {ch['detail']}")
        print("  Reminder: iPhone and computer on the same Wi-Fi, no 'client/AP isolation' (guest networks often isolate devices).")
    return 0 if all(ch["ok"] for ch in rep["checks"]) else 1


if __name__ == "__main__":
    sys.exit(main())
