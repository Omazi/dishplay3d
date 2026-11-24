#!/usr/bin/env python3
"""Does the calculator keep the computer awake while it works? Start a real calculator, send it one view the way
the iPhone does, and read what the SYSTEM says about requests against sleep.

  python tools/check_keep_awake.py        (exit code 0: the system holds a request from the calculator)

Windows: `powercfg /requests` (needs an administrator). Linux with systemd: `systemd-inhibit --list`.
The automatic check on a Windows machine runs this: nothing else can prove the call on a real Windows.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))


def requests_against_sleep() -> tuple[str, bool | None]:
    """(what the system says, whether a request of the calculator is in it; None when this system cannot be asked)."""
    if sys.platform == "win32":
        out = subprocess.run(["powercfg", "/requests"], capture_output=True, text=True).stdout
        system = out.split("SYSTEM:", 1)[1].split("AWAYMODE:", 1)[0] if "SYSTEM:" in out and "AWAYMODE:" in out else out
        return out, "python" in system.lower()
    if sys.platform.startswith("linux"):
        try:
            r = subprocess.run(["systemd-inhibit", "--list", "--no-pager"], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return "systemd-inhibit is not available on this system", None
        if r.returncode != 0:
            return "nothing answers systemd-inhibit on this system (a container?): " + r.stderr.strip(), None
        return r.stdout, "DishPlay Scan" in r.stdout
    return f"no check written for {sys.platform}", None


def main() -> int:
    import cv2
    from app.tls import fingerprint
    from scan_client import ScanClient
    from tests.helpers import box_json
    from tests.synthetic import SyntheticScene, frame_meta, orbit_poses

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        data = Path(tmp) / "data"
        log = open(Path(tmp) / "calculator.log", "w")
        proc = subprocess.Popen([sys.executable, "-m", "app.main", "--data", str(data), "--port", str(port), "--host", "127.0.0.1",
                                 "--code", "424242"], cwd=ROOT / "backend", stdout=log, stderr=subprocess.STDOUT)
        try:
            url, client = f"https://127.0.0.1:{port}", None
            for _ in range(240):
                if (data / "tls" / "server.crt").exists():
                    try:
                        client = ScanClient(url, fingerprint(data / "tls" / "server.crt"))
                        client.health()
                        break
                    except Exception:
                        client = None
                time.sleep(0.5)
            if client is None:
                print("the calculator did not start:\n" + (Path(tmp) / "calculator.log").read_text(errors="replace"))
                return 1
            before, _ = requests_against_sleep()
            client.pair("424242")
            sid = client.create_session(box_json(), {"platform": "synthetic", "model": "check", "lidar_available": False, "lidar_enabled": False})
            scene, pose = SyntheticScene(), orbit_poses(12)[0]
            image, _ = scene.render(pose)
            jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()
            client.put_frame(sid, frame_meta(scene, 0, pose, session_id=sid), jpeg)
            held = None
            for _ in range(20):                      # the calculator looks every half second
                time.sleep(0.5)
                said, held = requests_against_sleep()
                if held is not False:
                    break
            print("--- before the scan:\n" + before.strip())
            print("--- one view after the start of a scan:\n" + said.strip())
            if held is None:
                print("RESULT: this system cannot be asked; nothing was proved")
                return 0
            print("RESULT: " + ("the system holds a request of the calculator: the computer stays awake"
                                if held else "NO request of the calculator: the computer could go to sleep during a scan"))
            return 0 if held else 1
        finally:
            proc.terminate()            # on Windows this kills the calculator alone, as the Task Manager would
            try:
                proc.wait(20)
            except subprocess.TimeoutExpired:
                proc.kill()
            log.close()
            # The calculation process the calculator had started is now on its own. It must notice and stop by
            # itself. On Windows a file held by a running process cannot be removed, and that process holds
            # this log: the moment the file can be removed is the moment it stopped.
            start, stopped = time.time(), False
            while time.time() - start < 30:
                try:
                    (Path(tmp) / "calculator.log").unlink()
                    stopped = True
                    break
                except FileNotFoundError:
                    stopped = True
                    break
                except PermissionError:
                    time.sleep(0.5)
            if sys.platform == "win32":
                print(f"calculation process left alone: {'stopped by itself after %.1f s' % (time.time() - start) if stopped else 'STILL RUNNING after 30 s'}")
            if not stopped:
                sys.exit(1)


if __name__ == "__main__":
    sys.exit(main())
