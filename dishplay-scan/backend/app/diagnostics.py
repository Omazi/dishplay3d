"""Capability report of the calculator (used by /diagnostics and tools/doctor.py)."""
from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path


def _mem_total_bytes():
    try:
        if sys.platform.startswith("linux"):
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
        if sys.platform == "win32":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong), ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return int(m.ullTotalPhys)
    except Exception:
        return None
    return None


def capabilities(data_dir: str | None = None) -> dict:
    out = {"python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine(),
           "cpu_count": os.cpu_count(), "ram_bytes": _mem_total_bytes(), "wsl": "microsoft" in platform.release().lower()}
    try:
        import cv2
        out["opencv"] = cv2.__version__
        out["opencv_threads"] = cv2.getNumThreads()
        out["opencv_sift"] = hasattr(cv2, "SIFT_create")
    except Exception as exc:
        out["opencv_error"] = repr(exc)
    try:
        import open3d as o3d
        out["open3d"] = o3d.__version__
        out["open3d_cuda"] = bool(o3d.core.cuda.is_available())
    except Exception as exc:
        out["open3d_error"] = repr(exc)
    gpu = shutil.which("nvidia-smi")
    out["nvidia_smi"] = bool(gpu)
    out["gpu_required"] = False
    if data_dir:
        try:
            du = shutil.disk_usage(data_dir)
            out["disk_free_bytes"] = du.free
        except OSError:
            pass
    return out
