"""Keep the computer awake while the calculator works.

Nobody touches the PC while dishes are scanned one after the other, and a final calculation lasts a quarter of
an hour: with the usual power settings of a laptop the PC goes to sleep in the middle of it, and the app shows
"calculateur injoignable". The request is made only while the calculator works, and only for the system: the
screen may turn off.
"""
from __future__ import annotations

import shutil
import subprocess
import sys

ES_CONTINUOUS = 0x80000000          # Windows: "what I ask stays in effect until I say otherwise"
ES_SYSTEM_REQUIRED = 0x00000001     # Windows: do not go to sleep (the display may)

# Elsewhere a small program of the system holds the request for as long as it runs.
HOLDERS = {
    "linux": ("systemd-inhibit", ["--what=sleep", "--who=DishPlay Scan", "--why=scan ou calcul en cours", "--mode=block", "sleep", "infinity"]),
    "darwin": ("caffeinate", ["-i"]),
}


class KeepAwake:
    """set(True) asks the system not to sleep, set(False) gives the request back; asking twice changes nothing.

    On Windows the request belongs to the THREAD that makes it (SetThreadExecutionState): always call set()
    from the same thread, and one that lives as long as the calculator. Nothing here ever raises: a system
    that cannot be asked simply sleeps as it is set to."""

    def __init__(self, platform: str = sys.platform, kernel32=None, which=shutil.which, popen=subprocess.Popen):
        self.busy = False
        self._kernel32 = None
        self._program = None
        self._popen = popen
        self._holder = None
        self.how: str | None = None          # "windows", the name of the holding program, or None: no way to ask
        if platform == "win32":
            try:
                if kernel32 is None:
                    import ctypes
                    kernel32 = ctypes.windll.kernel32
                self._kernel32 = kernel32
                self.how = "windows"
            except Exception:
                pass
        elif platform in HOLDERS:
            name, args = HOLDERS[platform]
            path = which(name)
            if path:
                self._program = [path, *args]
                self.how = name

    def set(self, busy: bool) -> None:
        busy = bool(busy)
        if busy == self.busy:
            return
        self.busy = busy
        try:
            if self._kernel32 is not None:
                self._kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED if busy else ES_CONTINUOUS)
            elif self._program is not None:
                if busy:
                    self._holder = self._popen(self._program, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    self._release()
        except Exception:
            pass

    def _release(self):
        holder, self._holder = self._holder, None
        if holder is not None and holder.poll() is None:
            holder.terminate()
            try:
                holder.wait(timeout=2)
            except Exception:
                pass

    def close(self) -> None:
        """The calculator stops: leave nothing behind (on Windows the request ends with its thread)."""
        try:
            self._release()
        except Exception:
            pass
        self.busy = False
