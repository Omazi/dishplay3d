"""Linux process-lifetime checks using small Python sleepers, never real engines."""
import contextlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from worker import reconstruct as worker


ROOT = Path(__file__).resolve().parents[2]
ENGINE = """
import os, signal, sys, time
from pathlib import Path
signal.alarm(10)
Path(sys.argv[1], "engine.pid").write_text(str(os.getpid()))
time.sleep(10)
"""
PYTHON_WORKER = """
import os, signal, sys
from pathlib import Path
from worker import reconstruct as worker
def interrupt(signum, frame):
    raise KeyboardInterrupt()
signal.signal(signal.SIGTERM, interrupt)
signal.alarm(10)
worker.arm_parent_death(int(sys.argv[1]))
output = Path(sys.argv[2])
output.joinpath("worker.pid").write_text(str(os.getpid()))
# Parent death, rather than laptop free memory/disk, is the subject of this test.
worker.resource_guard = lambda *_: None
try:
    worker.execute_stage({"name": "dummy", "command": [sys.executable, "-c", sys.argv[3], str(output)]},
                         output, {"memory_mib": 128, "stage_seconds": 8})
except KeyboardInterrupt:
    output.joinpath("cancelled").write_text("engine cleanup completed")
    sys.exit(130)
"""
SUPERVISOR = """
import os, signal, subprocess, sys
signal.alarm(10)
child = subprocess.Popen([sys.executable, "-c", sys.argv[1], str(os.getpid()), sys.argv[2], sys.argv[3]],
                         start_new_session=True)
sys.exit(child.wait())
"""


def running(pid: int) -> bool:
    try:
        # An orphan can remain briefly as a zombie until the host reaps it.
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] not in ("Z", "X")
    except FileNotFoundError:
        return False


@unittest.skipUnless(sys.platform == "linux", "Linux prctl is required")
class ParentDeathTests(unittest.TestCase):
    def wait_until(self, predicate, description):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        self.fail(description)

    @contextlib.contextmanager
    def process_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            supervisor = subprocess.Popen(
                [sys.executable, "-c", SUPERVISOR, PYTHON_WORKER, directory, ENGINE],
                cwd=ROOT, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            try:
                self.wait_until(lambda: (output / "engine.pid").exists() and (output / "engine.pid").stat().st_size > 0,
                                "Dummy engine failed to start within 3 seconds")
                yield supervisor, output, int((output / "worker.pid").read_text()), int((output / "engine.pid").read_text())
            finally:
                # These PIDs belong only to the disposable test tree.
                for name in ("engine.pid", "worker.pid"):
                    try:
                        pid = int((output / name).read_text())
                        if running(pid):
                            os.kill(pid, signal.SIGKILL)
                    except (FileNotFoundError, ProcessLookupError, ValueError):
                        pass
                if supervisor.poll() is None:
                    supervisor.kill()
                supervisor.wait(timeout=3)
                supervisor.stderr.close()

    def test_supervisor_death_cancels_worker_and_engine(self):
        with self.process_tree() as (supervisor, output, python_pid, engine_pid):
            supervisor.kill()
            supervisor.wait(timeout=3)
            self.wait_until(lambda: (output / "cancelled").exists() and not running(python_pid) and not running(engine_pid),
                            "Killed supervisor left a running worker or engine")

    def test_abrupt_python_death_kills_engine(self):
        with self.process_tree() as (_, _output, python_pid, engine_pid):
            os.kill(python_pid, signal.SIGKILL)
            self.wait_until(lambda: not running(python_pid) and not running(engine_pid),
                            "Killed Python worker left a running engine")

    def test_parent_pid_race_terminates_before_work(self):
        process = subprocess.run(
            [sys.executable, "-c", "import os; from worker.reconstruct import arm_parent_death; "
             "arm_parent_death(os.getppid() + 1); print('unsafe continuation')"],
            cwd=ROOT, capture_output=True, timeout=3,
        )
        self.assertEqual(process.returncode, -signal.SIGTERM, process.stderr.decode())
        self.assertNotIn(b"unsafe continuation", process.stdout)

    def test_invalid_supervisor_pid_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "parent PID"):
            worker.arm_parent_death(0)


if __name__ == "__main__":
    unittest.main()
