"""Capability report of the calculator (used by /diagnostics and tools/doctor.py)."""
from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

MIN_FREE_BYTES = 500 * 1024 ** 2    # below this the calculator refuses new views and new scans (HTTP 507)
LOW_FREE_BYTES = 5 * 1024 ** 3      # below this it warns: a scan takes 100 to 300 MB


def free_bytes(path) -> int | None:
    """Free space on the disk that holds `path`, or that will hold it when the folder does not exist yet
    (None when it cannot be read)."""
    p = Path(path)
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        return int(shutil.disk_usage(p).free)
    except OSError:
        return None


def human_size(n: float) -> str:
    """A size as a person writes it in French: 212,4 Mo ; 50 Go."""
    for unit, size in (("Go", 1024 ** 3), ("Mo", 1024 ** 2), ("ko", 1024)):
        if n >= size:
            return f"{n / size:.1f}".replace(".0", "").replace(".", ",") + f" {unit}"
    return f"{int(n)} octets"


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
    try:
        import onnxruntime
        out["onnxruntime"] = onnxruntime.__version__
    except Exception as exc:
        out["onnxruntime_error"] = repr(exc)
    try:
        from reconstruction.mono_depth import model_path
        mp = model_path(None) if not data_dir else Path(data_dir) / "models" / model_path(None).name
        out["depth_model"] = mp.exists()
    except Exception:
        out["depth_model"] = False
    gpu = shutil.which("nvidia-smi")
    out["nvidia_smi"] = bool(gpu)
    out["gpu_required"] = False
    if data_dir:
        free = free_bytes(data_dir)
        if free is not None:
            out["disk_free_bytes"] = free
            out["disk_low"] = free < LOW_FREE_BYTES          # worth making room (tools/clean_sessions.py)
            out["disk_full"] = free < MIN_FREE_BYTES         # new views are refused until room is made
            out["disk_min_free_bytes"] = MIN_FREE_BYTES
    return out
