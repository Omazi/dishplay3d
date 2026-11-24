"""The real worker (app/worker.py), run inside the test instead of in a process of its own: what it tells
the server when the final calculation ends well, raises, or builds nothing."""
import queue

from app.worker import FAILURE_TEXT, worker_main
from tests.helpers import box_json

SETTINGS = {"mono": False, "mono_live": False, "neural": False, "texture": False}
REPORT = {"mesh": {"vertices": 300, "triangles": 500}, "texture": {"status": "ok"}, "scale_check": None,
          "footprint_width": {"x": 0.2, "z": 0.2}, "timings_s": {"total": 1.0}}


def run_finish(tmp_path, monkeypatch, finish_session=None):
    """Start the worker on an empty session, ask it to finish, stop it; what it emitted, in order."""
    sdir = tmp_path / "sessions" / "20260101-120000-abcdef"
    (sdir / "frames").mkdir(parents=True)
    if finish_session is not None:
        monkeypatch.setattr("reconstruction.refinement.finish_session", finish_session)
    cmd_q, evt_q = queue.Queue(), queue.Queue()
    cmd_q.put(("finish", None))
    cmd_q.put(("stop",))
    worker_main(cmd_q, evt_q, str(sdir), box_json(), SETTINGS, [])
    return list(evt_q.queue)


def delivering(report):
    def finish_session(engine, out_dir, **kwargs):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "model.glb").write_bytes(b"glTF")
        (out_dir / "manifest.json").write_text("{}")
        return report
    return finish_session


def kinds(events):
    return [(e["type"], e.get("state") or e.get("code")) for e in events if e["type"] in ("status", "error", "artifacts", "finish_over")]


def test_a_finished_model_is_announced_then_the_end_of_the_whole_command(tmp_path, monkeypatch):
    verdict = {"level": "good", "score": 88, "issues": []}
    fallbacks = [{"code": "texture_vertex_colours", "message": "Couleurs simplifiées."}]
    events = run_finish(tmp_path, monkeypatch, delivering({**REPORT, "verdict": verdict, "fallbacks": fallbacks}))
    assert kinds(events) == [("status", "capturing"), ("status", "finishing"), ("artifacts", None), ("status", "done"), ("finish_over", None)]
    artifacts = [e for e in events if e["type"] == "artifacts"][0]
    assert artifacts["files"] == ["manifest.json", "model.glb"]
    assert artifacts["report"] == {**REPORT, "verdict": verdict, "fallbacks": fallbacks}
    assert events[-1] == {"type": "finish_over", "ok": True, "session_id": "20260101-120000-abcdef"}


def test_a_report_without_verdict_is_still_delivered(tmp_path, monkeypatch):
    events = run_finish(tmp_path, monkeypatch, delivering(dict(REPORT)))    # an engine that does not give a verdict yet
    artifacts = [e for e in events if e["type"] == "artifacts"][0]
    assert artifacts["report"] == REPORT
    assert events[-1]["type"] == "finish_over" and events[-1]["ok"] is True


def test_an_exception_while_finishing_is_reported_as_the_end_of_the_command(tmp_path, monkeypatch):
    def full_disk(engine, out_dir, **kwargs):
        raise OSError(28, "No space left on device")
    events = run_finish(tmp_path, monkeypatch, full_disk)
    assert kinds(events) == [("status", "capturing"), ("status", "finishing"), ("error", "worker_exception"), ("finish_over", None)]
    over = events[-1]
    assert (over["ok"], over["reason"]) == (False, "disk_full")
    assert "No space left on device" in over["detail"] and "OSError" in over["trace"] and "full_disk" in over["trace"]
    # App 1.7.0 shows the first 140 characters of this message to the person: a sentence, not Python.
    error = [e for e in events if e["type"] == "error"][0]
    assert error["message"] == FAILURE_TEXT["disk_full"] and len(error["message"]) <= 140
    assert "No space left on device" in error["detail"]


def test_every_failure_sentence_fits_in_what_the_published_app_shows():
    for reason, sentence in FAILURE_TEXT.items():
        assert 20 < len(sentence) <= 140 and "\n" not in sentence, reason


def test_a_final_calculation_that_built_nothing_is_not_announced_as_a_model(tmp_path, monkeypatch):
    events = run_finish(tmp_path, monkeypatch)      # the real final step, on a session without any view
    assert not (tmp_path / "sessions" / "20260101-120000-abcdef" / "final" / "model.glb").exists()
    assert kinds(events) == [("status", "capturing"), ("status", "finishing"), ("error", "no_model"), ("finish_over", None)]
    assert (events[-1]["ok"], events[-1]["reason"]) == (False, "no_model")


class Parent:
    """What multiprocessing.parent_process() gives a calculation process: the calculator that started it."""

    def __init__(self, alive):
        self.alive = alive

    def is_alive(self):
        return self.alive


def run_as_child(tmp_path, monkeypatch, parent, commands=()):
    import signal

    import app.worker
    sdir = tmp_path / "sessions" / "20260101-120000-abcdef"
    (sdir / "frames").mkdir(parents=True)
    handlers = []
    monkeypatch.setattr(app.worker.multiprocessing, "parent_process", lambda: parent)
    monkeypatch.setattr(app.worker.signal, "signal", lambda sig, handler: handlers.append((sig, handler)))
    cmd_q, evt_q = queue.Queue(), queue.Queue()
    for c in commands:
        cmd_q.put(c)
    worker_main(cmd_q, evt_q, str(sdir), box_json(), SETTINGS, [])
    return handlers, list(evt_q.queue), signal


def test_the_calculation_process_leaves_ctrl_c_to_the_calculator(tmp_path, monkeypatch):
    # Ctrl+C in the calculator's terminal reaches this process too; the calculator stops it itself.
    handlers, _, signal = run_as_child(tmp_path, monkeypatch, Parent(alive=True), [("stop",)])
    assert handlers == [(signal.SIGINT, signal.SIG_IGN)]


def test_a_calculation_process_whose_calculator_is_gone_stops_by_itself(tmp_path, monkeypatch):
    # No "stop" will ever come from a calculator that was killed: the process must not stay behind for ever.
    _, events, _ = run_as_child(tmp_path, monkeypatch, Parent(alive=False))     # returns: it did not wait for a "stop"
    assert events == []     # and says nothing: there is nobody left to tell (it used to announce "capturing" first)


def test_a_final_calculation_whose_calculator_was_killed_stops_instead_of_writing_next_to_its_successor(tmp_path, monkeypatch):
    # A calculator that is killed (not closed) leaves its calculation process behind. When it starts again it
    # gives the dish to a new process: the old one must not go on writing in the same folder for minutes.
    import app.worker
    parent = Parent(alive=True)
    reached = []

    def finish_session(engine, out_dir, emit=None, **kwargs):
        parent.alive = False                                  # the calculator is killed during the calculation
        emit({"type": "finish_progress", "step": "depth", "done": 1, "total": 10})   # the next thing it says...
        reached.append("went on")                             # ...must be the last thing it does
        return delivering(REPORT)(engine, out_dir)

    monkeypatch.setattr("reconstruction.refinement.finish_session", finish_session)
    sdir = tmp_path / "sessions" / "20260101-120000-abcdef"
    (sdir / "frames").mkdir(parents=True)
    monkeypatch.setattr(app.worker.multiprocessing, "parent_process", lambda: parent)
    monkeypatch.setattr(app.worker.signal, "signal", lambda sig, handler: None)
    cmd_q, evt_q = queue.Queue(), queue.Queue()
    cmd_q.put(("finish", None))
    worker_main(cmd_q, evt_q, str(sdir), box_json(), SETTINGS, [])       # returns: it does not wait for a "stop"
    assert reached == [] and not (sdir / "final" / "model.glb").exists()
    said = [(e["type"], e.get("state") or e.get("code")) for e in evt_q.queue]
    assert ("artifacts", None) not in said and ("finish_progress", None) not in said and "finish_over" not in [k for k, _ in said]
