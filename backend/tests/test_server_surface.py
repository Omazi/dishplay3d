"""What the calculator offers to any device of the local network, paired or not: as little as possible.
No description pages of the API, small bodies outside the views, a pairing that cannot be blocked for ever."""
import time

from app import main
from app.store import Store
from tests.test_server_fakes import SESSION, calc, frame_body  # noqa: F401  (calc is a fixture)


def test_the_description_pages_of_the_api_are_not_served(calc):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert calc.client.get(path).status_code == 404, path
        assert calc.client.get(path, headers=calc.auth).status_code == 404, path


def test_health_names_the_active_session_only_to_a_paired_phone(calc):
    a = calc.create()
    anonymous = calc.client.get("/health").json()
    assert anonymous["service"] == "dishplay-scan" and anonymous["api"] == main.API_VERSION      # what pairing needs
    assert "active_session" in anonymous and anonymous["active_session"] is None
    assert calc.client.get("/health", headers={"Authorization": "Bearer wrong"}).json()["active_session"] is None
    paired = calc.client.get("/health", headers=calc.auth).json()
    assert paired["active_session"] == a and paired["worker_alive"] is True


def test_every_route_but_health_and_pairing_asks_for_the_token(calc):
    a = calc.create()
    for method, path in (("GET", "/diagnostics"), ("POST", "/sessions"), ("GET", f"/sessions/{a}"),
                         ("POST", f"/sessions/{a}/resume_worker"), ("PUT", f"/sessions/{a}/frames/0"),
                         ("POST", f"/sessions/{a}/box"), ("POST", f"/sessions/{a}/pause"), ("POST", f"/sessions/{a}/resume"),
                         ("POST", f"/sessions/{a}/finish"), ("POST", f"/sessions/{a}/name"), ("GET", f"/sessions/{a}/preview/latest"),
                         ("GET", f"/sessions/{a}/artifacts"), ("GET", f"/sessions/{a}/artifacts/model.glb")):
        r = calc.client.request(method, path, content=b"{}")
        assert r.status_code == 401, (method, path, r.status_code)


def test_the_name_given_in_the_app_is_kept_with_the_dish(calc):
    """Until now the name never left the iPhone: on the PC every dish was a folder named after a date."""
    a = calc.create()
    assert calc.info(a)["name"] is None
    r = calc.post(f"/sessions/{a}/name", {"name": "  Tajine aux\npruneaux \x07 "})
    assert r.status_code == 200 and r.json() == {"ok": True, "name": "Tajine aux pruneaux"}      # one clean line
    assert calc.info(a)["name"] == "Tajine aux pruneaux"
    folder = calc.server.store.session_dir(a)
    assert (folder / "nom.txt").read_text(encoding="utf-8") == "Tajine aux pruneaux\n"           # readable on the PC without any tool
    # Renamed in the app: the new name replaces the old one.
    assert calc.post(f"/sessions/{a}/name", {"name": "Tajine d'agneau"}).status_code == 200
    assert calc.info(a)["name"] == "Tajine d'agneau"
    assert (folder / "nom.txt").read_text(encoding="utf-8") == "Tajine d'agneau\n"
    # A long name is cut, an empty or odd one is refused, an unknown dish is unknown.
    assert len(calc.post(f"/sessions/{a}/name", {"name": "x" * 500}).json()["name"]) == 120
    for bad in ({"name": "   "}, {"name": 12}, {}, {"name": None}):
        assert calc.post(f"/sessions/{a}/name", bad).status_code == 422, bad
    assert calc.post("/sessions/unknown-dish/name", {"name": "Tajine"}).status_code == 404
    # The name changes nothing for the scan itself.
    assert calc.info(a)["state"] == "capturing"


def test_pairing_answers_a_malformed_request_without_an_error_500(calc):
    for body in (b"[1, 2]", b'"424242"', b"not json at all", b"", b"\xff\xfe"):
        r = calc.client.post("/pair", content=body, headers={"Content-Type": "application/json"})
        assert r.status_code in (400, 422), (body, r.status_code, r.text)
    assert calc.client.post("/pair", json={"code": "é" * 6}).status_code == 403      # not ASCII: a wrong code, nothing more
    assert calc.client.post("/pair", json={"code": 424242}).status_code == 200       # the right one, typed as a number


def test_bodies_that_are_not_views_are_limited_to_a_small_size(calc):
    a = calc.create()
    big = b'{"code": "' + b"0" * (2 * 1024 * 1024) + b'"}'
    assert calc.client.post("/pair", content=big).status_code == 413
    for path in ("/sessions", f"/sessions/{a}/box", f"/sessions/{a}/finish"):
        r = calc.client.post(path, content=big, headers=calc.auth)
        assert r.status_code == 413, (path, r.status_code)
    # The limit holds when the size is not announced (body sent in pieces, no Content-Length).
    pieces = (big[i:i + 65536] for i in range(0, len(big), 65536))
    assert calc.client.post("/pair", content=pieces).status_code == 413
    # Ordinary requests still pass.
    assert calc.client.post("/sessions", json=SESSION, headers=calc.auth).status_code == 200
    assert calc.post(f"/sessions/{a}/finish", {"reference_width_m": 0.2}).status_code == 200


def test_a_view_larger_than_the_limit_is_refused_even_when_its_size_is_not_announced(calc, monkeypatch):
    monkeypatch.setattr(main, "MAX_BODY", 256 * 1024)
    a = calc.create()
    big = frame_body(a, 0) + b"\0" * (300 * 1024)
    assert calc.client.put(f"/sessions/{a}/frames/0", content=big, headers=calc.auth).status_code == 413
    pieces = (big[i:i + 65536] for i in range(0, len(big), 65536))
    assert calc.client.put(f"/sessions/{a}/frames/0", content=pieces, headers=calc.auth).status_code == 413
    assert calc.put_frame(a, 0).status_code == 200


def wrong_codes(calc, n):
    return [calc.client.post("/pair", json={"code": "000000"}).status_code for _ in range(n)]


def test_wrong_codes_block_pairing_for_a_while_not_for_ever(calc, monkeypatch, capsys):
    monkeypatch.setattr(main, "PAIR_BLOCK_S", 1.5)
    assert wrong_codes(calc, 8) == [403] * 8
    r = calc.client.post("/pair", json={"code": "424242"})
    assert r.status_code == 429, "after 8 wrong codes even the right one is refused for a while"
    assert "attendez" in r.json()["detail"].lower() and int(r.headers["retry-after"]) >= 1
    assert wrong_codes(calc, 3) == [429] * 3
    assert len([line for line in capsys.readouterr().out.splitlines() if "jumelage" in line.lower()]) == 1
    time.sleep(1.6)
    r = calc.client.post("/pair", json={"code": "424242"})      # trying during the block did not make it longer
    assert r.status_code == 200 and r.json()["token"]


def test_a_successful_pairing_forgets_the_wrong_codes_before_it(calc):
    assert wrong_codes(calc, 7) == [403] * 7
    assert calc.client.post("/pair", json={"code": "424242"}).status_code == 200
    assert wrong_codes(calc, 7) == [403] * 7
    assert calc.client.post("/pair", json={"code": "424242"}).status_code == 200


def test_the_calculator_can_forget_every_paired_device(tmp_path, monkeypatch, capsys):
    from tests.test_server_tls import run_main
    store = Store(tmp_path)
    store.add_token("token-of-a-lost-iphone", "iPhone")
    store.add_token("token-of-another", "iPhone")
    store.db.close()
    run_main(monkeypatch, capsys, tmp_path, "--insecure-http")
    store = Store(tmp_path)
    assert store.token_ok("token-of-a-lost-iphone")             # an ordinary start forgets nobody
    store.db.close()
    _, out = run_main(monkeypatch, capsys, tmp_path, "--insecure-http", "--forget-devices")
    store = Store(tmp_path)
    assert not store.token_ok("token-of-a-lost-iphone") and not store.token_ok("token-of-another")
    store.db.close()
    assert [line for line in out.splitlines() if "2 appareil" in line], out
