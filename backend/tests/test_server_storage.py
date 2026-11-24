"""The disk of the PC: a full disk is a clear refusal (HTTP 507 and a French sentence), never an error 500
without a word; free space is shown at startup and in /diagnostics. The calculation processes are fake."""
import collections
import errno
import shutil
import sqlite3
from pathlib import Path

from app import diagnostics
from tests.test_server_fakes import SESSION, Console, calc, frame_body, wait_for  # noqa: F401  (calc is a fixture)

GB = 1024 ** 3
Usage = collections.namedtuple("Usage", "total used free")


def disk(monkeypatch, free):
    monkeypatch.setattr(shutil, "disk_usage", lambda path: Usage(500 * GB, 500 * GB - free, free))


def readable_refusal(r):
    """HTTP 507 with one French sentence about the disk, as the app shows it (it shows `detail`)."""
    assert r.status_code == 507, (r.status_code, r.text)
    detail = r.json()["detail"]
    assert isinstance(detail, str) and "disque" in detail and 20 < len(detail) < 200 and "Error" not in detail, detail
    return detail


def stored_files(calc, sid):
    return sorted(p.name for p in (calc.data / "sessions" / sid / "frames").iterdir())


def test_a_view_is_refused_clearly_when_the_disk_is_almost_full(calc, monkeypatch, capsys):
    a = calc.create()
    assert calc.put_frame(a, 0).status_code == 200
    disk(monkeypatch, free=100 * 1024 ** 2)
    readable_refusal(calc.put_frame(a, 1))
    readable_refusal(calc.put_frame(a, 2))
    assert stored_files(calc, a) == ["000000.jpg", "000000.json"] and sum(calc.info(a)["frames"].values()) == 1
    console = Console(capsys)
    assert len(console.lines("disque")) == 1, "one line on the PC console, not one per refused view"
    disk(monkeypatch, free=50 * GB)              # the person made room: the same views are accepted
    assert calc.put_frame(a, 1).status_code == 200 and calc.put_frame(a, 2).status_code == 200
    assert sum(calc.info(a)["frames"].values()) == 3


def test_a_write_that_fails_for_lack_of_space_is_a_clear_refusal_and_leaves_nothing_behind(calc, monkeypatch):
    a = calc.create()
    real_write = Path.write_text

    def full(self, *args, **kwargs):             # the picture fits, the metadata written after it does not
        if self.parent.name == "frames":
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_write(self, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", full)
    readable_refusal(calc.put_frame(a, 0))
    assert stored_files(calc, a) == [] and calc.info(a)["frames"] == {}
    monkeypatch.setattr(Path, "write_text", real_write)
    r = calc.put_frame(a, 0)
    assert r.status_code == 200 and r.json()["duplicate"] is False


def test_a_database_that_cannot_grow_is_a_clear_refusal_too(calc, monkeypatch):
    a = calc.create()

    def full(*args, **kwargs):
        raise sqlite3.OperationalError("database or disk is full")
    real = calc.server.store.add_frame
    monkeypatch.setattr(calc.server.store, "add_frame", full)
    readable_refusal(calc.put_frame(a, 0))
    assert stored_files(calc, a) == []
    monkeypatch.setattr(calc.server.store, "add_frame", real)
    assert calc.put_frame(a, 0).status_code == 200


def test_another_write_error_is_refused_with_its_reason_and_written_to_the_log(calc, monkeypatch):
    a = calc.create()
    real_write = Path.write_bytes

    def denied(self, *args, **kwargs):
        if self.parent.name == "frames":
            raise PermissionError(errno.EACCES, "Permission denied")
        return real_write(self, *args, **kwargs)
    monkeypatch.setattr(Path, "write_bytes", denied)
    r = calc.put_frame(a, 0)
    assert r.status_code == 507 and "enregistrer" in r.json()["detail"], r.text
    assert "Permission denied" in (calc.data / "calculateur.log").read_text(encoding="utf-8")


def test_a_new_scan_is_refused_clearly_when_the_disk_is_almost_full(calc, monkeypatch):
    before = sorted(p.name for p in (calc.data / "sessions").iterdir())
    disk(monkeypatch, free=100 * 1024 ** 2)
    readable_refusal(calc.client.post("/sessions", json=SESSION, headers=calc.auth))
    assert sorted(p.name for p in (calc.data / "sessions").iterdir()) == before, "a session was created all the same"
    assert calc.procs() == []


def test_diagnostics_show_the_free_space(calc, monkeypatch):
    disk(monkeypatch, free=50 * GB)
    d = calc.client.get("/diagnostics", headers=calc.auth).json()
    assert (d["disk_free_bytes"], d["disk_low"], d["disk_full"]) == (50 * GB, False, False)
    disk(monkeypatch, free=2 * GB)
    d = calc.client.get("/diagnostics", headers=calc.auth).json()
    assert (d["disk_free_bytes"], d["disk_low"], d["disk_full"]) == (2 * GB, True, False)
    disk(monkeypatch, free=100 * 1024 ** 2)
    d = calc.client.get("/diagnostics", headers=calc.auth).json()
    assert (d["disk_low"], d["disk_full"]) == (True, True)
    assert d["disk_min_free_bytes"] == diagnostics.MIN_FREE_BYTES


def test_the_console_shows_the_free_space_at_startup(tmp_path, monkeypatch, capsys):
    from tests.test_server_tls import run_main
    disk(monkeypatch, free=50 * GB)
    _, out = run_main(monkeypatch, capsys, tmp_path, "--insecure-http")
    line = [x for x in out.splitlines() if "Espace libre" in x]
    assert len(line) == 1 and "50" in line[0] and "Go" in line[0], out
    assert "ATTENTION" not in out
    disk(monkeypatch, free=100 * 1024 ** 2)
    _, out = run_main(monkeypatch, capsys, tmp_path, "--insecure-http")
    assert [x for x in out.splitlines() if "ATTENTION" in x and "disque" in x], out


def test_the_calculator_no_longer_knows_a_scan_whose_folder_was_removed(calc):
    a = calc.create()
    calc.put_frames(a, 2)
    b = calc.create()                            # the calculator now works for another scan
    wait_for(lambda: calc.info(a)["active"] is False, what="the first scan to lose its process")
    shutil.rmtree(calc.data / "sessions" / a)    # what tools/clean_sessions.py does to an old scan without model
    assert calc.client.get(f"/sessions/{a}", headers=calc.auth).status_code == 404
    assert calc.put_frame(a, 2).status_code == 404
    assert calc.finish(a).status_code == 404
    assert calc.post(f"/sessions/{a}/resume_worker").status_code == 404
    assert calc.info(b)["active"] is True and calc.procs(a)[-1].stopped


def run_doctor(monkeypatch, capsys, data):
    import json
    import sys

    import doctor
    monkeypatch.setenv("DISHPLAY_DATA", str(data))
    monkeypatch.setattr(sys, "argv", ["doctor.py", "--quick", "--json", "--port", "0"])
    capsys.readouterr()
    code = doctor.main()
    report = json.loads(capsys.readouterr().out)
    return code, report, [c for c in report["checks"] if "disque" in c["name"]]


def test_the_doctor_checks_the_free_space_of_the_data_disk(tmp_path, monkeypatch, capsys):
    data = tmp_path / "not" / "created" / "yet"          # before the first start of the calculator
    disk(monkeypatch, free=50 * GB)
    _, report, checks = run_doctor(monkeypatch, capsys, data)
    assert len(checks) == 1 and checks[0]["ok"] is True and "50 Go" in checks[0]["detail"], report["checks"]
    assert report["capabilities"]["disk_free_bytes"] == 50 * GB and not data.exists()
    disk(monkeypatch, free=2 * GB)                       # usable, but worth a word
    _, _, checks = run_doctor(monkeypatch, capsys, data)
    assert checks[0]["ok"] is True and "clean_sessions" in checks[0]["detail"]
    disk(monkeypatch, free=100 * 1024 ** 2)              # the calculator would refuse every view
    code, _, checks = run_doctor(monkeypatch, capsys, data)
    assert checks[0]["ok"] is False and "clean_sessions" in checks[0]["detail"] and code == 1
