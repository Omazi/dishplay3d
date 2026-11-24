"""A final calculation that goes wrong: the dish is marked as failed (and stays so), the person is told in
plain French on the phone and on the PC, the details go to calculateur.log, and the next dish gets its turn.
The calculation processes are fake (tests/test_server_fakes.py)."""
import threading

from app import main
from tests.test_server_fakes import Console, Listener, calc, wait_for  # noqa: F401  (calc is a fixture)
from tests.test_server_queue import start_finishing


def failed(calc, sid):
    return wait_for(lambda: (i := calc.info(sid))["state"] == "failed" and i, what="the dish to be marked as failed")


def readable(sentence):
    """One short sentence for a person: no line break, no Python in it."""
    return isinstance(sentence, str) and 20 < len(sentence) < 200 and "\n" not in sentence \
        and "Error" not in sentence and "Traceback" not in sentence


def test_an_exception_in_the_final_calculation_fails_the_dish_and_frees_the_queue(calc, capsys):
    calc.ctx.outcome = "raise"
    a, pa = start_finishing(calc)
    calc.ctx.outcome = "ok"
    b = calc.create()
    assert calc.finish(b).status_code == 200
    with calc.events(a) as ws:
        phone = Listener(ws)
        pa.release()
        info = failed(calc, a)
        assert (info["failed"], info["active"], info["ready"], info["queued"]) == (True, False, False, False)
        assert readable(info["error"]), info["error"]
        status = wait_for(lambda: [e for e in phone.of("status") if e["state"] == "failed"], what="the failed status on the phone")[0]
        assert status["error"] == info["error"]
        assert [e["code"] for e in phone.of("error")] == ["worker_exception"]      # the event the app already knows
        assert not phone.of("finish_over"), "an internal event reached the phone"
    console = Console(capsys)
    wait_for(lambda: console.lines(a), what="a line about this dish on the PC console")
    calc.finishing(b)                 # the queue moves on by itself
    assert len(console.lines(a)) == 1 and info["error"] in console.lines(a)[0], console.lines(a)
    log = (calc.data / "calculateur.log").read_text(encoding="utf-8")
    assert a in log and "Traceback" in log and "RuntimeError: boom in the engine" in log
    assert pa.stopped, "the process of the failed calculation was kept"


def test_a_failed_dish_stays_failed_after_a_restart_and_can_be_finished_again(calc):
    calc.ctx.outcome = "raise"
    a, pa = start_finishing(calc)
    pa.release()
    error = failed(calc, a)["error"]
    calc.restart()
    info = calc.info(a)
    assert (info["state"], info["failed"], info["error"], info["active"]) == ("failed", True, error, False)
    with calc.events(a) as ws:        # a phone that connects now is told at once
        phone = Listener(ws)
        status = wait_for(lambda: phone.of("status"), what="the last known status")[0]
        assert (status["state"], status["error"]) == ("failed", error)
    assert calc.procs() == [], "a failed calculation must not start again by itself"

    calc.ctx.outcome = "ok"
    r = calc.finish(a)
    assert (r.status_code, r.json()["queued"]) == (200, False)
    p2 = calc.finishing(a)
    info = calc.info(a)
    assert (info["state"], info["failed"], info["error"], info["active"]) == ("finishing", False, None, True)
    p2.release()
    info = wait_for(lambda: (i := calc.info(a))["state"] == "done" and i, what="the dish to be ready")
    assert (info["ready"], info["failed"], info["error"]) == (True, False, None)


def test_a_process_that_dies_while_finishing_is_noticed_without_any_event(calc, capsys):
    a, pa = start_finishing(calc)
    b = calc.create()
    assert calc.finish(b).status_code == 200
    with calc.events(a) as ws:
        phone = Listener(ws)
        wait_for(lambda: phone.of("hello"), what="the phone to be connected")
        pa.kill()                     # killed for lack of memory, for example: it says nothing
        info = failed(calc, a)
        assert (info["failed"], info["active"], info["ready"]) == (True, False, False)
        assert readable(info["error"]), info["error"]
        status = wait_for(lambda: [e for e in phone.of("status") if e["state"] == "failed"], what="the failed status on the phone")[0]
        assert status["error"] == info["error"]
        # App 1.7.0 only shows "error" events: without one it would say nothing at all.
        assert [e["code"] for e in phone.of("error")] == ["worker_died"]
    console = Console(capsys)
    wait_for(lambda: console.lines(a), what="a line about this dish on the PC console")
    calc.finishing(b)                 # the next dish is not blocked
    assert len(console.lines(a)) == 1 and info["error"] in console.lines(a)[0], console.lines(a)
    assert a in (calc.data / "calculateur.log").read_text(encoding="utf-8")


def test_a_dead_process_is_noticed_even_when_its_event_pipe_cannot_be_read(calc, monkeypatch):
    monkeypatch.setattr(main, "STUCK_PUMP_S", 0.3, raising=False)
    a, pa = start_finishing(calc)
    # A process killed in the middle of a message leaves a pipe on which reading never returns.
    pa.evt_q.get = lambda *args, **kwargs: threading.Event().wait()
    pa.kill()
    info = failed(calc, a)
    assert (info["failed"], info["active"]) == (True, False)


def test_a_final_calculation_that_built_no_model_is_a_failure_not_a_ready_dish(calc):
    calc.ctx.outcome = "no_model"     # e.g. no usable view at all: the engine ends normally, with nothing
    a, pa = start_finishing(calc)
    pa.release()
    info = failed(calc, a)
    assert (calc.data / "sessions" / a / "final" / "manifest.json").exists()
    assert (info["ready"], info["failed"], info["active"]) == (False, True, False)
    assert readable(info["error"]) and "vue" in info["error"]
    assert calc.client.get(f"/sessions/{a}/artifacts", headers=calc.auth).json()["ready"] is False


def test_a_process_that_dies_after_delivering_the_model_does_not_fail_the_dish(calc):
    calc.ctx.linger_after_done = True
    a, pa = start_finishing(calc)
    b = calc.create()
    assert calc.finish(b).status_code == 200
    pa.release()
    wait_for(lambda: calc.info(a)["state"] == "done", what="the model to be delivered")
    pa.kill()                         # dies in the optional step that follows (neural rendering)
    calc.finishing(b)
    info = calc.info(a)
    assert (info["state"], info["failed"], info["ready"], info["error"]) == ("done", False, True, None)


def test_a_live_worker_that_dies_is_started_again_by_the_next_view(calc, capsys):
    a = calc.create()
    calc.put_frames(a, 2)
    pa = calc.proc(a)
    pa.kill()
    wait_for(lambda: calc.info(a)["active"] is False, what="the death to be noticed")
    assert calc.info(a)["failed"] is False          # a scan in progress is not a failed dish
    wait_for(lambda: Console(capsys).lines(a), what="a line about this scan on the PC console")
    assert calc.put_frame(a, 2).json()["queued"] is True
    assert len(calc.procs(a)) == 2 and len(calc.procs(a)[-1].existing) == 3


def test_a_live_worker_that_keeps_dying_is_not_restarted_for_ever(calc):
    a = calc.create()
    for n in range(3):
        calc.proc(a)
        wait_for(lambda: calc.info(a)["active"], what="the worker to be active")
        calc.procs(a)[-1].kill()
        wait_for(lambda: calc.info(a)["active"] is False, what="the death to be noticed")
        r = calc.put_frame(a, n)
        assert r.status_code == 200
    assert len(calc.procs(a)) == 3 and r.json()["queued"] is False     # the views are kept, nothing more is started
    assert calc.finish(a).status_code == 200                              # asking for the model still works
    assert len(calc.finishing(a).existing) == 3


def test_an_idle_process_that_dies_after_its_dish_was_delivered_alarms_nobody(calc, capsys):
    a, pa = start_finishing(calc)
    pa.release()
    wait_for(lambda: calc.info(a)["state"] == "done" and not calc.server.active.finishing, what="the whole command to be over")
    with calc.events(a) as ws:
        phone = Listener(ws)
        wait_for(lambda: phone.of("hello"), what="the phone to be connected")
        pa.kill()                     # the process that stayed behind is closed by the system, for example
        wait_for(lambda: calc.server.active is None, what="the death to be noticed")
        ws.send_text("ping")          # what the server had to say about it has reached the phone before this answer
        wait_for(lambda: phone.of("pong"), what="the answer to the ping")
        info = calc.info(a)
        assert (info["state"], info["ready"], info["failed"]) == ("done", True, False)
        assert phone.of("error") == [], "the phone was told of a problem with a dish that is ready"
    assert Console(capsys).lines(a) == [], "the PC console announced a problem with a dish that is ready"
    assert a in (calc.data / "calculateur.log").read_text(encoding="utf-8")
