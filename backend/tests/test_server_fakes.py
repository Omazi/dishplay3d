"""Stand-ins for the reconstruction process, so the calculator's queue is tested in milliseconds.

The server is the real one (routes, store, threads, WebSocket). Only the heavy process is replaced: a
FakeProcess speaks the worker's protocol (app/worker.py) and computes nothing. The test decides when a final
calculation ends, and how. No test lives in this file: it holds what the test_server_*.py files share.
"""
import hashlib
import json
import queue
import shutil
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from reconstruction.preview_format import encode_frame
from tests.helpers import box_json

SESSION = {"schema": "dishplay.session/1", "box": box_json(), "device": {"platform": "synthetic", "model": "test"}}
TRACE = 'Traceback (most recent call last):\n  File "refinement.py", line 1, in finish_session\nRuntimeError: boom in the engine\n'
VERDICT = {"level": "fair", "score": 61, "issues": ["holes"], "top_coverage": 0.8, "measured_share": 0.7,
           "raggedness": 18.0, "sides_seen": 1.0, "views": 40}
FALLBACKS = [{"code": "texture_vertex_colours", "message": "La texture n'a pas pu être posée : couleurs simplifiées."}]


def wait_for(cond, timeout=5.0, what="the expected state"):
    """The value of cond() as soon as it is true; the test fails when it never is."""
    end = time.monotonic() + timeout
    while True:
        value = cond()
        if value:
            return value
        if time.monotonic() > end:
            raise AssertionError(f"timed out after {timeout} s waiting for {what}")
        time.sleep(0.01)


def frame_body(sid: str, fid: int) -> bytes:
    """One view as the iPhone sends it (DPF1 envelope). The server never decodes the picture."""
    jpg = b"\xff\xd8\xff" + f"view {fid} of {sid}".encode()
    meta = {"schema": "dishplay.frame/1", "session_id": sid, "frame_id": fid, "epoch": 0, "timestamp_s": fid * 0.4,
            "image": {"width": 640, "height": 480, "encoding": "jpeg", "orientation": "sensor_native",
                      "sha256": hashlib.sha256(jpg).hexdigest()},
            "intrinsics": {"fx": 500.0, "fy": 500.0, "cx": 319.5, "cy": 239.5, "width": 640, "height": 480},
            "distortion": {"status": "none_synthetic"},
            "T_world_from_cameraAR": [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.4, 0.0, 0.0, 0.0, 1.0],
            "tracking": {"state": "normal"}}
    return encode_frame(meta, jpg)


class FakeProcess:
    """One calculation process. It reads the server's commands and answers like app/worker.py."""

    def __init__(self, ctx, args, name):
        self.ctx = ctx
        self.cmd_q, self.evt_q, session_dir, self.box, self.settings, self.existing = args
        self.dir = Path(session_dir)
        self.sid = self.dir.name
        self.name = name
        self.commands: list[tuple] = []       # everything the server sent to this process
        self.terminated = False
        self.exitcode = None
        self.outcome = ctx.outcome
        self.linger_after_done = ctx.linger_after_done
        self._alive = False
        self._gate = threading.Event()        # opened by the test: the final calculation may end
        self._over = threading.Event()        # opened by the test: the optional step after "done" may end
        self._thread = threading.Thread(target=self._run, daemon=True)

    # --- what multiprocessing.Process offers
    def start(self):
        self._alive = True
        self.ctx.started.append(self)
        self._thread.start()

    def is_alive(self):
        return self._alive

    def join(self, timeout=None):
        self._thread.join(timeout)

    def terminate(self):
        self.terminated = True
        self._alive = False
        self.exitcode = -15

    # --- what the test does to it
    def release(self):
        """Let the final calculation end (in the way given by `outcome`)."""
        self._gate.set()

    def release_optional_step(self):
        self._over.set()

    def kill(self):
        """The process dies at once and says nothing, like a process killed for lack of memory."""
        self._alive = False
        self.exitcode = -9

    @property
    def stopped(self):
        """True when the server asked this process to stop, or killed it."""
        return ("stop",) in self.commands or self.terminated

    def finish_commands(self):
        return [c for c in self.commands if c[0] == "finish"]

    def emit(self, ev):
        ev.setdefault("session_id", self.sid)
        self.evt_q.put(ev)

    # --- the worker's protocol
    def _run(self):
        self.emit({"type": "status", "state": "capturing", "queue": len(self.existing)})
        while self._alive:
            try:
                cmd = self.cmd_q.get(timeout=0.01)
            except queue.Empty:
                continue
            self.commands.append(cmd)
            if cmd[0] == "stop":
                self._alive = False
                self.exitcode = 0
            elif cmd[0] == "frame":
                self.emit({"type": "frame", "frame_id": json.loads(Path(cmd[1]).read_text())["frame_id"], "status": "integrated"})
            elif cmd[0] == "finish":
                self._finish()

    def _wait(self, gate):
        while self._alive:
            if gate.wait(0.01):
                return True
        return False

    def _finish(self):
        self.emit({"type": "status", "state": "finishing", "queue": 0})
        self.emit({"type": "finish_progress", "step": "depth", "done": 3, "total": 10})
        if not self._wait(self._gate):
            return
        final = self.dir / "final"
        final.mkdir(parents=True, exist_ok=True)
        if self.outcome == "raise":
            self.emit({"type": "error", "code": "worker_exception", "message": "RuntimeError('boom in the engine')", "trace": TRACE})
            self.emit({"type": "finish_over", "ok": False, "reason": "exception", "detail": "RuntimeError('boom in the engine')", "trace": TRACE})
            return
        if self.outcome == "no_model":   # the engine ran to its end with nothing to build: files, but no model
            (final / "manifest.json").write_text(json.dumps({"schema": "dishplay.manifest/1", "files": ["report.json"]}))
            (final / "report.json").write_text(json.dumps({"mesh": {"vertices": 0, "triangles": 0}}))
            self.emit({"type": "error", "code": "no_model", "message": "Aucune vue utilisable."})
            self.emit({"type": "finish_over", "ok": False, "reason": "no_model"})
            return
        (final / "model.glb").write_bytes(b"glTF fake model")
        (final / "report.json").write_text(json.dumps({"mesh": {"vertices": 300, "triangles": 500}, "verdict": VERDICT, "fallbacks": FALLBACKS}))
        (final / "manifest.json").write_text(json.dumps({"schema": "dishplay.manifest/1", "files": ["model.glb", "report.json"]}))
        self.emit({"type": "artifacts", "files": ["manifest.json", "model.glb", "report.json"],
                   "report": {"mesh": {"vertices": 300, "triangles": 500}, "verdict": VERDICT, "fallbacks": FALLBACKS}})
        self.emit({"type": "status", "state": "done", "queue": 0})
        if self.linger_after_done and not self._wait(self._over):
            return
        self.emit({"type": "finish_over", "ok": True})


class FakeContext:
    """Takes the place of multiprocessing's context: the same Queue() and Process() calls."""

    def __init__(self):
        self.started: list[FakeProcess] = []
        self.outcome = "ok"               # how the final calculations started from now on end: ok | raise | no_model
        self.linger_after_done = False    # an optional step keeps the process busy after "done" (like the neural one)

    def Queue(self):
        return queue.Queue()

    def Process(self, target=None, args=(), daemon=None, name=None):
        return FakeProcess(self, args, name)


class Listener(threading.Thread):
    """Collects what one events socket receives, so a test never blocks on a message that does not come."""

    def __init__(self, ws):
        super().__init__(daemon=True)
        self.ws = ws
        self.events: list[dict] = []
        self.start()

    def run(self):
        try:
            while True:
                self.events.append(self.ws.receive_json())
        except Exception:
            pass

    def of(self, kind):
        return [e for e in self.events if e.get("type") == kind]

    def states(self):
        return [e["state"] for e in self.of("status")]


class Console:
    """What the calculator printed on the PC console so far (it prints from its own threads)."""

    def __init__(self, capsys):
        self.capsys = capsys
        self.text = ""

    def lines(self, containing: str) -> list[str]:
        self.text += self.capsys.readouterr().out
        return [line for line in self.text.splitlines() if containing in line]


class Calc:
    """A calculator whose calculation processes are fake, and a paired phone that talks to it."""

    def __init__(self, data: Path, monkeypatch):
        self.data = data
        self.ctx = FakeContext()
        monkeypatch.setattr(main.mp, "get_context", lambda method=None: self.ctx)
        monkeypatch.setattr(main, "WATCH_S", 0.05, raising=False)     # how often the server looks at its process
        monkeypatch.setattr(main, "STOP_WAIT_S", 0.2, raising=False)  # how long a process asked to stop is waited for
        monkeypatch.setattr(main, "DEATH_GRACE_S", 0.1, raising=False)    # how long after a death the server concludes
        self._closed = []
        self._mark = 0
        self._open()
        token = self.client.post("/pair", json={"code": "424242", "device": "test"}).json()["token"]
        self.auth = {"Authorization": f"Bearer {token}"}

    def _open(self):
        self.server = main.Server(self.data, "424242")
        self.client = TestClient(main.create_app(self.server))
        self.client.__enter__()

    # --- the phone
    def create(self) -> str:
        r = self.client.post("/sessions", json=SESSION, headers=self.auth)
        assert r.status_code == 200, r.text
        return r.json()["session_id"]

    def put_frame(self, sid, fid):
        return self.client.put(f"/sessions/{sid}/frames/{fid}", content=frame_body(sid, fid), headers=self.auth)

    def put_frames(self, sid, n):
        for fid in range(n):
            assert self.put_frame(sid, fid).status_code == 200

    def post(self, path, body=None):
        return self.client.post(path, json=body or {}, headers=self.auth)

    def finish(self, sid):
        return self.post(f"/sessions/{sid}/finish")

    def info(self, sid) -> dict:
        r = self.client.get(f"/sessions/{sid}", headers=self.auth)
        assert r.status_code == 200, r.text
        return r.json()

    def events(self, sid):
        return self.client.websocket_connect(f"/sessions/{sid}/events", headers=self.auth)

    # --- the calculation processes
    def procs(self, sid=None) -> list[FakeProcess]:
        """Processes started since the calculator was last (re)started, oldest first."""
        return [p for p in self.ctx.started[self._mark:] if sid is None or p.sid == sid]

    def proc(self, sid) -> FakeProcess:
        return wait_for(lambda: self.procs(sid), what=f"a calculation process for {sid}")[-1]

    def finishing(self, sid) -> FakeProcess:
        """The process of this session, once it has received the order to finish."""
        return wait_for(lambda: [p for p in self.procs(sid) if p.finish_commands() and p.is_alive()],
                        what=f"the final calculation of {sid} to start")[-1]

    def alive(self) -> list[FakeProcess]:
        return [p for p in self.ctx.started if p.is_alive()]

    # --- the computer
    def restart(self, power_cut=False):
        """Stop the calculator and start it again on the same data. With power_cut the calculator gets no
        chance to tidy up: the new one starts from the files exactly as they were at that instant."""
        if power_cut:
            copy = self.data.parent / f"{self.data.name}-cut{len(self._closed)}"
            shutil.copytree(self.data, copy)
            self._closed.append(self.client)      # the old one is left as it is; closed at the end of the test
            self.data = copy
        else:
            self.client.__exit__(None, None, None)
        self._mark = len(self.ctx.started)
        self._open()

    def close(self):
        for client in [self.client, *self._closed]:
            client.__exit__(None, None, None)
        for p in self.ctx.started:
            p.kill()


@pytest.fixture
def calc(tmp_path, monkeypatch):
    c = Calc(tmp_path / "data", monkeypatch)
    yield c
    c.close()
