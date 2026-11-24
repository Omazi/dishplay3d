"""One final calculation at a time, and a real queue: what the iPhone app relies on when several dishes are
scanned in a row. The calculation processes are fake (tests/test_server_fakes.py); everything else is real."""
import time
from pathlib import Path

from app import main
from tests.test_server_fakes import SESSION, Listener, calc, wait_for  # noqa: F401  (calc is a fixture)


def start_finishing(calc, frames=3):
    """A dish whose final calculation is running (and stays running until the test releases it)."""
    sid = calc.create()
    calc.put_frames(sid, frames)
    assert calc.finish(sid).status_code == 200
    return sid, calc.finishing(sid)


# ----------------------------------------------------------------------------------- two dishes in a row

def test_a_new_scan_never_stops_the_dish_being_finished(calc):
    a, pa = start_finishing(calc)
    r = calc.client.post("/sessions", json=SESSION, headers=calc.auth)
    assert r.status_code == 200
    body = r.json()
    b = body["session_id"]
    time.sleep(0.2)
    assert pa.is_alive() and not pa.stopped, "the dish being finished lost its calculation"
    assert calc.procs(b) == [], "one calculation process at a time"
    assert body["events"] == f"/sessions/{b}/events" and body["lidar_used"] is False and body.get("waiting") is True
    calc.put_frames(b, 3)    # its views are accepted and kept meanwhile
    info = calc.info(b)
    assert info["frames"] == {"received": 3}
    assert (info["waiting"], info["active"], info["busy_with_other"], info["state"]) == (True, False, True, "capturing")
    ia = calc.info(a)
    assert (ia["active"], ia["state"], ia["busy_with_other"], ia["waiting"]) == (True, "finishing", False, False)
    assert ia["progress"] == {"step": "depth", "done": 3, "total": 10}

    pa.release()
    wait_for(lambda: calc.info(a)["ready"], what="the first dish to be ready")
    pb = calc.proc(b)       # the live worker of the second scan starts by itself...
    assert [Path(p).name for p, _ in pb.existing] == ["000000.json", "000001.json", "000002.json"]   # ...from the stored views
    info = wait_for(lambda: (i := calc.info(b))["active"] and i, what="the second scan to get its worker")
    assert (info["waiting"], info["busy_with_other"], info["state"]) == (False, False, "capturing")
    assert calc.info(a)["state"] == "done"
    assert len(calc.alive()) == 1


def test_a_session_created_when_the_calculator_is_free_is_not_waiting(calc):
    r = calc.client.post("/sessions", json=SESSION, headers=calc.auth)
    assert r.json()["waiting"] is False
    sid = r.json()["session_id"]
    assert calc.proc(sid).existing == []
    info = calc.info(sid)
    assert (info["active"], info["waiting"], info["queued"], info["queue_position"], info["failed"], info["error"]) == \
        (True, False, False, None, False, None)
    assert (info["verdict"], info["fallbacks"]) == (None, [])


def test_finish_requests_wait_their_turn_and_start_by_themselves(calc):
    a, pa = start_finishing(calc)
    b = calc.create()
    calc.put_frames(b, 2)
    c = calc.create()
    calc.put_frames(c, 4)
    rb, rc = calc.finish(b), calc.finish(c)
    assert (rb.status_code, rc.status_code) == (200, 200), "a finish request must wait its turn, not be refused"
    assert {k: rb.json()[k] for k in ("ok", "queued", "position")} == {"ok": True, "queued": True, "position": 1}
    assert {k: rc.json()[k] for k in ("ok", "queued", "position")} == {"ok": True, "queued": True, "position": 2}
    ib, ic = calc.info(b), calc.info(c)
    assert (ib["queued"], ib["queue_position"], ib["state"], ib["active"], ib["busy_with_other"]) == (True, 1, "queued", False, True)
    assert (ic["queued"], ic["queue_position"], ic["state"], ic["active"], ic["busy_with_other"]) == (True, 2, "queued", False, True)
    assert pa.is_alive() and not pa.stopped and calc.procs(b) == [] and calc.procs(c) == []

    pa.release()
    pb = calc.finishing(b)      # the oldest request first, without anybody asking again
    assert len(pb.existing) == 2 and pb.finish_commands() == [("finish", None)]
    ib = wait_for(lambda: (i := calc.info(b))["state"] == "finishing" and i, what="the second dish to be in calculation")
    assert (ib["active"], ib["queued"], ib["queue_position"], ib["busy_with_other"]) == (True, False, None, False)
    ic = calc.info(c)
    assert (ic["queued"], ic["queue_position"], ic["active"], ic["busy_with_other"]) == (True, 1, False, True)
    assert calc.procs(c) == [] and calc.info(a)["ready"]

    pb.release()
    pc = calc.finishing(c)
    assert len(pc.existing) == 4
    pc.release()
    wait_for(lambda: calc.info(c)["ready"] and calc.info(b)["ready"], what="every dish to be ready")
    assert [p.sid for p in calc.procs() if p.finish_commands()] == [a, b, c]


def test_a_finish_request_keeps_its_reference_width_while_it_waits(calc):
    a, pa = start_finishing(calc)
    b = calc.create()
    r = calc.post(f"/sessions/{b}/finish", {"reference_width_m": 0.24})
    assert r.status_code == 200 and r.json()["queued"] is True
    pa.release()
    assert calc.finishing(b).finish_commands() == [("finish", 0.24)]


def test_a_second_finish_request_does_not_calculate_twice(calc):
    a, pa = start_finishing(calc)
    again = calc.finish(a)          # e.g. the scanner left behind and the home screen both ask
    assert again.status_code == 200
    pa.release()
    wait_for(lambda: calc.info(a)["ready"], what="the dish to be ready")
    time.sleep(0.3)
    assert len(pa.finish_commands()) == 1, "the final model was calculated twice"
    assert {k: again.json()[k] for k in ("ok", "queued", "position")} == {"ok": True, "queued": False, "position": 0}


def test_a_second_finish_request_for_a_waiting_dish_keeps_its_place(calc):
    a, pa = start_finishing(calc)
    b, c = calc.create(), calc.create()
    assert calc.finish(b).status_code == 200 and calc.finish(c).status_code == 200
    again = calc.finish(b)
    assert (again.status_code, again.json()["queued"], again.json()["position"]) == (200, True, 1)
    assert (calc.info(b)["queue_position"], calc.info(c)["queue_position"]) == (1, 2)
    pa.release()
    pb = calc.finishing(b)
    pb.release()
    pc = calc.finishing(c)
    pc.release()
    wait_for(lambda: calc.info(c)["ready"], what="the last dish to be ready")
    time.sleep(0.3)
    assert [p.sid for p in calc.procs() if p.finish_commands()] == [a, b, c]
    assert [len(p.finish_commands()) for p in (pa, pb, pc)] == [1, 1, 1]


def test_the_optional_step_after_done_is_not_cut_short_by_the_queue(calc):
    calc.ctx.linger_after_done = True
    a, pa = start_finishing(calc)
    b = calc.create()
    r = calc.finish(b)
    assert r.status_code == 200 and r.json()["queued"] is True
    pa.release()
    wait_for(lambda: calc.info(a)["state"] == "done", what="the first dish to be delivered")
    time.sleep(0.3)             # "done" is out, but the process is still working for this dish (neural step)
    assert pa.is_alive() and not pa.stopped and calc.procs(b) == []
    ib = calc.info(b)
    assert (ib["queued"], ib["busy_with_other"]) == (True, True)
    pa.release_optional_step()
    calc.finishing(b)


def test_when_the_calculator_is_free_finish_requests_go_first_then_the_most_recent_waiting_scan(calc):
    a, pa = start_finishing(calc)
    b = calc.create()               # two scans opened while the first dish is being calculated...
    calc.put_frames(b, 1)
    d = calc.create()
    calc.put_frames(d, 2)
    c = calc.create()               # ...and a third one whose final model is asked for
    calc.put_frames(c, 3)
    assert calc.finish(c).json()["queued"] is True
    calc.put_frame(d, 2)            # the scan that sent a view last is the one still going on
    assert [calc.info(s)["waiting"] for s in (b, d, c)] == [True, True, False]
    pa.release()
    pc = calc.finishing(c)          # the finish request first
    time.sleep(0.2)
    assert calc.procs(b)[1:] == [] and calc.procs(d)[1:] == [], "a waiting scan went before a finish request"
    pc.release()
    wait_for(lambda: calc.info(d)["active"], what="the most recent waiting scan to get its worker")
    assert len(calc.procs(d)[-1].existing) == 3
    time.sleep(0.2)
    ib = calc.info(b)               # the older one stays without worker; its next view will ask for one
    assert (ib["active"], ib["waiting"]) == (False, False) and len(calc.alive()) == 1


# ------------------------------------------------------------------- sessions that have no worker (yet)

def test_reopening_a_dish_while_another_is_finished_waits_and_stops_nothing(calc):
    b = calc.create()
    calc.put_frames(b, 2)
    a, pa = start_finishing(calc)          # the calculator now belongs to the dish being finished
    r = calc.post(f"/sessions/{b}/resume_worker")
    assert (r.status_code, r.json()) == (200, {"ok": True, "waiting": True})
    time.sleep(0.2)
    assert pa.is_alive() and not pa.stopped
    assert calc.info(b)["waiting"] is True
    pa.release()
    wait_for(lambda: calc.info(b)["active"], what="the reopened dish to get its worker")
    assert len(calc.procs(b)[-1].existing) == 2 and calc.info(b)["waiting"] is False


def test_reopening_a_known_dish_always_answers_200(calc):
    a = calc.create()
    assert calc.post(f"/sessions/{a}/resume_worker").json() == {"ok": True, "note": "already active"}
    calc.put_frames(a, 2)
    calc.restart()
    assert calc.procs() == []
    assert calc.post(f"/sessions/{a}/resume_worker").json() == {"ok": True}
    assert len(calc.proc(a).existing) == 2
    assert calc.post("/sessions/nobody-knows-me/resume_worker").status_code == 404


def test_views_sent_after_a_restart_of_the_calculator_restart_the_live_worker(calc):
    a = calc.create()
    calc.put_frames(a, 3)
    calc.restart()
    r = calc.put_frame(a, 3)
    assert r.status_code == 200 and r.json()["queued"] is True
    pa = calc.proc(a)
    assert len(pa.existing) == 4            # resume mode: every stored view, the new one included
    assert calc.put_frame(a, 4).json()["queued"] is True
    wait_for(lambda: [c for c in pa.commands if c[0] == "frame"], what="the next view to reach the worker")
    assert len(calc.procs()) == 1
    info = calc.info(a)
    assert (info["active"], info["frames"].get("received", 0) + info["frames"].get("integrated", 0)) == (True, 5)
    r = calc.finish(a)
    assert (r.status_code, r.json()["queued"], r.json()["position"]) == (200, False, 0)
    assert calc.finishing(a) is pa


def test_finish_works_for_a_session_without_worker(calc):
    a = calc.create()
    calc.put_frames(a, 3)
    calc.restart()
    r = calc.finish(a)
    assert r.status_code == 200
    assert {k: r.json()[k] for k in ("ok", "queued", "position")} == {"ok": True, "queued": False, "position": 0}
    pa = calc.finishing(a)
    assert len(pa.existing) == 3
    info = calc.info(a)
    assert (info["state"], info["active"]) == ("finishing", True)
    pa.release()
    wait_for(lambda: calc.info(a)["ready"], what="the dish to be ready")


def test_views_never_take_the_calculator_from_a_dish_being_finished(calc):
    b = calc.create()
    a, pa = start_finishing(calc)
    r = calc.put_frame(b, 0)
    assert r.status_code == 200 and r.json()["queued"] is False
    time.sleep(0.2)
    assert pa.is_alive() and not pa.stopped and len(calc.procs(b)) == 1     # only its first worker, stopped since
    assert calc.info(b)["frames"] == {"received": 1}
    pa.release()            # once the calculator is free the scan that is still sending views gets its worker back
    wait_for(lambda: calc.info(b)["active"], what="the scan to get its worker back")
    assert len(calc.procs(b)[-1].existing) == 1


def test_views_do_not_take_the_calculator_from_a_scan_that_is_still_sending(calc, monkeypatch):
    monkeypatch.setattr(main, "CAPTURE_GRACE_S", 2.0, raising=False)
    b = calc.create()
    calc.put_frame(b, 0)
    a = calc.create()            # a new scan takes the calculator, as it always did
    pa = calc.proc(a)
    calc.put_frame(a, 0)
    r = calc.put_frame(b, 1)     # the older scan sends a view: kept, but the scan in progress keeps the calculator
    assert r.status_code == 200 and r.json()["queued"] is False
    time.sleep(0.2)
    assert pa.is_alive() and not pa.stopped and calc.info(a)["active"] is True
    time.sleep(2.0)              # the scan in progress has been silent for longer than the grace period
    assert calc.put_frame(b, 2).json()["queued"] is True
    assert pa.stopped
    assert len(calc.procs(b)[-1].existing) == 3 and calc.info(b)["active"] is True


def test_a_finish_request_waits_for_a_scan_that_is_still_sending(calc, monkeypatch):
    monkeypatch.setattr(main, "CAPTURE_GRACE_S", 1.5, raising=False)
    b = calc.create()
    calc.put_frames(b, 2)
    a = calc.create()
    pa = calc.proc(a)
    calc.put_frame(a, 0)
    r = calc.finish(b)           # e.g. "Terminer ce plat" on a second iPhone while the first one is scanning
    assert r.status_code == 200 and (r.json()["queued"], r.json()["position"]) == (True, 1)
    assert pa.is_alive() and not pa.stopped
    assert calc.info(b)["busy_with_other"] is True
    pb = calc.finishing(b)       # ... and starts by itself once the scan has stopped sending views
    assert pa.stopped and len(pb.existing) == 2


def test_a_dish_that_asks_to_finish_lets_the_older_request_go_first(calc, monkeypatch):
    monkeypatch.setattr(main, "CAPTURE_GRACE_S", 30.0, raising=False)
    b = calc.create()
    calc.put_frames(b, 2)
    a = calc.create()
    calc.put_frame(a, 0)
    r = calc.finish(b)
    assert r.status_code == 200 and r.json()["position"] == 1      # waits for the scan in progress
    r = calc.finish(a)                                   # the scan in progress is over: first in, first out
    pb = calc.finishing(b)                               # the older request starts at once, in the place of the live worker
    assert (r.json()["queued"], r.json()["position"]) == (True, 1)      # and this one is the next
    assert calc.info(a)["queue_position"] == 1 and calc.procs(a)[-1].stopped
    pb.release()
    pa = calc.finishing(a)
    assert len(pa.existing) == 1


# ----------------------------------------------------------------------------------------- what GET says

def test_a_dead_process_is_not_reported_as_active(calc):
    a = calc.create()
    pa = calc.proc(a)
    assert calc.info(a)["active"] is True
    pa.kill()
    wait_for(lambda: calc.info(a)["active"] is False, what="the dead process to stop counting as active")
    health = calc.client.get("/health").json()
    assert health["worker_alive"] is False


def test_the_session_tells_the_verdict_and_the_fallbacks_of_its_final_model(calc):
    from tests.test_server_fakes import FALLBACKS, VERDICT
    a, pa = start_finishing(calc)
    assert (calc.info(a)["verdict"], calc.info(a)["fallbacks"]) == (None, [])
    pa.release()
    info = wait_for(lambda: (i := calc.info(a))["state"] == "done" and i, what="the dish to be ready")
    assert info["ready"] is True and info["verdict"] == VERDICT and info["fallbacks"] == FALLBACKS
    assert (info["failed"], info["error"]) == (False, None)
