"""The calculator is stopped while dishes are being calculated or are waiting: at the next start they get
their turn again, in the same order, once. The calculation processes are fake (tests/test_server_fakes.py)."""
import time

import pytest

from tests.test_server_fakes import calc, wait_for  # noqa: F401  (calc is a fixture)
from tests.test_server_queue import start_finishing


@pytest.mark.parametrize("power_cut", [False, True], ids=["closed normally", "power cut"])
def test_calculations_interrupted_by_a_restart_get_their_turn_again_in_order(calc, power_cut):
    a, pa = start_finishing(calc)
    b = calc.create()
    calc.put_frames(b, 2)
    assert calc.finish(b).status_code == 200
    c = calc.create()
    assert calc.finish(c).status_code == 200
    d = calc.create()                   # a scan that never asked for its model
    calc.put_frames(d, 1)

    calc.restart(power_cut=power_cut)
    pa2 = calc.finishing(a)             # nobody asks: the calculator picks up where it was
    assert len(pa2.existing) == 3 and pa2.finish_commands() == [("finish", None)]
    ia, ib, ic, i_d = (calc.info(s) for s in (a, b, c, d))
    assert (ia["state"], ia["active"], ia["failed"]) == ("finishing", True, False)
    assert (ib["state"], ib["queued"], ib["queue_position"], ib["busy_with_other"]) == ("queued", True, 1, True)
    assert (ic["state"], ic["queued"], ic["queue_position"]) == ("queued", True, 2)
    assert (i_d["state"], i_d["queued"], i_d["active"]) == ("capturing", False, False)

    pa2.release()
    pb = calc.finishing(b)
    assert len(pb.existing) == 2
    pb.release()
    calc.finishing(c).release()
    wait_for(lambda: all(calc.info(s)["ready"] for s in (a, b, c)), what="the three dishes to be ready")
    assert [p.sid for p in calc.procs()] == [a, b, c]
    assert calc.info(d)["ready"] is False


def test_a_calculation_interrupted_twice_is_not_started_a_third_time(calc):
    a, pa = start_finishing(calc)
    b = calc.create()
    assert calc.finish(b).status_code == 200
    calc.restart(power_cut=True)
    calc.finishing(a)                   # queued again, once
    calc.restart(power_cut=True)        # the calculator went down again during the same calculation
    info = wait_for(lambda: (i := calc.info(a))["state"] == "failed" and i, what="the dish to be marked as failed")
    assert info["failed"] is True and "deux fois" in info["error"]
    calc.finishing(b)                   # the dish that only waited keeps its turn
    assert calc.procs(a) == []
    r = calc.finish(a)                  # and the person can still ask again
    assert (r.status_code, r.json()["queued"], r.json()["position"]) == (200, True, 1)


def test_a_finished_dish_is_not_calculated_again_after_a_restart(calc):
    a, pa = start_finishing(calc)
    pa.release()
    wait_for(lambda: calc.info(a)["state"] == "done", what="the dish to be ready")
    time.sleep(0.3)                     # the process has told the server that the whole command is over
    calc.restart(power_cut=True)
    assert calc.procs() == [] and calc.info(a)["state"] == "done"


def test_a_delivered_dish_is_not_calculated_again_when_the_calculator_stops_in_the_optional_step(calc):
    calc.ctx.linger_after_done = True
    a, pa = start_finishing(calc)
    pa.release()
    wait_for(lambda: calc.info(a)["state"] == "done", what="the model to be delivered")
    time.sleep(0.2)                     # the process is still busy with the optional step (neural rendering)
    assert pa.is_alive() and not pa.stopped
    calc.restart(power_cut=True)
    time.sleep(0.3)
    assert calc.procs() == [], "a model that was already delivered was calculated again"
    info = calc.info(a)
    assert (info["state"], info["ready"], info["queued"]) == ("done", True, False)


def test_the_console_says_at_startup_which_calculations_are_taken_up_again(calc, monkeypatch, capsys):
    from tests.test_server_tls import run_main
    a, pa = start_finishing(calc)
    calc.client.__exit__(None, None, None)          # the calculator is closed while the dish is being calculated
    capsys.readouterr()
    _, out = run_main(monkeypatch, capsys, calc.data, "--insecure-http")      # started again, as `python -m app.main` does
    lines = [line for line in out.splitlines() if a in line]
    assert len(lines) == 1 and "Reprise" in lines[0] and "1 plat" in lines[0], out
    assert [p.sid for p in calc.ctx.started[-1:]] == [a] and calc.ctx.started[-1].finish_commands() == [("finish", None)]


def test_a_calculator_closed_together_with_its_calculation_process_does_not_call_it_a_failure(calc, monkeypatch, capsys):
    """Closing the window of the calculator, or Ctrl+C in it, ends the calculation process a moment before
    the calculator itself: that is a stop, to be taken up again at the next start, not a failed dish."""
    from app import main
    from tests.test_server_fakes import Console
    monkeypatch.setattr(main, "DEATH_GRACE_S", 3.0)
    a, pa = start_finishing(calc)
    pa.kill()                           # the system closes the calculation process first...
    time.sleep(0.3)
    calc.restart()                      # ...and the calculator right after; then it is started again
    assert Console(capsys).lines("CHEC") == [], "a stop of the calculator was announced as a failed calculation"
    info = calc.info(a)
    assert info["failed"] is False and info["state"] in ("queued", "finishing"), info["state"]
    calc.finishing(a).release()
    wait_for(lambda: calc.info(a)["ready"], what="the dish to be ready")
