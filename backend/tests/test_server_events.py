"""The events socket belongs to a session, not to its calculation process: a phone connected before the
process exists receives the events once it starts. The processes are fake (tests/test_server_fakes.py)."""
from tests.test_server_fakes import VERDICT, Listener, calc, wait_for  # noqa: F401  (calc is a fixture)
from tests.test_server_queue import start_finishing


def geometry(sid, version):
    return {"type": "geometry", "url": f"/sessions/{sid}/preview/{version}", "bytes": 1234,
            "header": {"schema": "dishplay.geometry/1", "version": version, "kind": "points+mesh"}}


def test_a_phone_connected_before_the_worker_exists_receives_its_events(calc):
    a = calc.create()
    calc.put_frames(a, 2)
    calc.restart()                      # the session is known, but nothing works on it
    with calc.events(a) as ws:
        phone = Listener(ws)
        hello = wait_for(lambda: phone.of("hello"), what="hello")[0]
        assert (hello["session_id"], hello["active"]) == (a, False)
        assert calc.post(f"/sessions/{a}/resume_worker").status_code == 200
        # The status sent by the process itself (it says how many stored views it took over), not a remembered one.
        wait_for(lambda: [e for e in phone.of("status") if e.get("queue") == 2], what="the status of the worker that just started")
        calc.proc(a).emit(geometry(a, 7))
        got = wait_for(lambda: phone.of("geometry"), what="the geometry of the worker that just started")[0]
        assert got["header"]["version"] == 7 and got["session_id"] == a


def test_a_phone_whose_dish_waits_follows_it_until_the_model(calc):
    a, pa = start_finishing(calc)
    b = calc.create()
    with calc.events(b) as ws:
        phone = Listener(ws)
        hello = wait_for(lambda: phone.of("hello"), what="hello")[0]
        assert hello["active"] is False
        assert calc.finish(b).status_code == 200
        queued = wait_for(lambda: [e for e in phone.of("status") if e["state"] == "queued"], what="the queued status")[0]
        assert queued["queue_position"] == 1
        pa.release()
        pb = calc.finishing(b)
        wait_for(lambda: "finishing" in phone.states(), what="the finishing status")
        pb.release()
        artifacts = wait_for(lambda: phone.of("artifacts"), what="the files of the model")[0]
        assert artifacts["report"]["verdict"] == VERDICT and "model.glb" in artifacts["files"]
        wait_for(lambda: "done" in phone.states(), what="the done status")
        states = phone.states()
        # The process starts in capture mode before it reads the order to finish: the phone must not be told
        # that its dish went back to "capturing" after "queued".
        assert "capturing" not in states[states.index("queued"):], states
        assert not phone.of("finish_over"), "an internal event reached the phone"


def test_a_new_connection_receives_the_last_known_status_and_geometry(calc):
    a = calc.create()
    calc.proc(a).emit(geometry(a, 3))
    wait_for(lambda: calc.info(a)["last_geometry"], what="the geometry to be known")
    with calc.events(a) as ws:
        phone = Listener(ws)
        wait_for(lambda: len(phone.events) >= 3, what="hello, status and geometry")
        assert [e["type"] for e in phone.events[:3]] == ["hello", "status", "geometry"]
        assert (phone.events[0]["active"], phone.events[1]["state"], phone.events[2]["header"]["version"]) == (True, "capturing", 3)
    calc.create()                       # another scan takes the calculator: the first one has no process any more
    wait_for(lambda: calc.info(a)["active"] is False, what="the first scan to lose its process")
    with calc.events(a) as ws:
        phone = Listener(ws)
        wait_for(lambda: len(phone.events) >= 3, what="hello, status and geometry without a process")
        assert [e["type"] for e in phone.events[:3]] == ["hello", "status", "geometry"]
        assert (phone.events[0]["active"], phone.events[2]["header"]["version"]) == (False, 3)


def test_the_socket_refuses_an_unknown_session_or_a_missing_token(calc):
    import pytest
    from starlette.websockets import WebSocketDisconnect
    a = calc.create()
    for path, headers in ((f"/sessions/{a}/events", {}), ("/sessions/nobody-knows-me/events", calc.auth)):
        with pytest.raises(WebSocketDisconnect) as e:
            with calc.client.websocket_connect(path, headers=headers):
                pass
        assert e.value.code == 4401


def test_everything_a_phone_receives_follows_the_contract(calc):
    """contracts/preview-message.schema.json describes the events; the app is written against it."""
    import json
    from pathlib import Path

    import jsonschema
    schema = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "preview-message.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema)
    a, pa = start_finishing(calc)
    calc.ctx.outcome = "raise"
    b = calc.create()
    received = []
    with calc.events(b) as ws:
        phone = Listener(ws)
        assert calc.finish(b).status_code == 200            # queued behind the first dish
        wait_for(lambda: "queued" in phone.states(), what="the queued status")
        ws.send_text("ping")
        wait_for(lambda: phone.of("pong"), what="the answer to the ping")
        pa.release()
        calc.finishing(b).release()                         # the second calculation fails
        wait_for(lambda: "failed" in phone.states(), what="the failed status")
        received += phone.events
    with calc.events(a) as ws:                              # the first dish was delivered meanwhile
        phone = Listener(ws)
        wait_for(lambda: phone.of("status"), what="the last known status")
        received += phone.events
    calc.ctx.outcome = "ok"
    with calc.events(b) as ws:
        phone = Listener(ws)
        assert calc.finish(b).status_code == 200            # asked again: this time the model is delivered
        calc.finishing(b).release()
        wait_for(lambda: "done" in phone.states(), what="the done status")
        received += phone.events
    kinds = {(e["type"], e.get("state")) for e in received}
    assert {("hello", None), ("pong", None), ("status", "queued"), ("status", "finishing"), ("status", "failed"),
            ("status", "done"), ("finish_progress", None), ("artifacts", None), ("error", None)} <= kinds, kinds
    for ev in received:
        errors = [e.message for e in validator.iter_errors(ev)]
        assert not errors, (ev, errors)
    props = {b["properties"]["type"]["const"]: b["properties"] for b in schema["oneOf"]}
    assert {"error", "queue_position"} <= set(props["status"]) and "active" in props["hello"]   # documented, not only tolerated
