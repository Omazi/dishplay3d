"""tools/clean_sessions.py: making room on the PC. It removes nothing unless asked (--apply), never a recent
scan, never a dish that waits for its calculation, and never a final model unless asked explicitly."""
import os
import time

import pytest

import clean_sessions
from app.store import Store
from tests.test_server_fakes import calc, wait_for  # noqa: F401  (calc is a fixture)

DAY = 86400.0
MB = 1024 ** 2


def make_session(data, sid, age_days, model=True, frames=3, previews=2):
    """A session folder as the calculator leaves it; every file was last touched `age_days` ago."""
    d = data / "sessions" / sid
    for sub in ("frames", "preview", "final"):
        (d / sub).mkdir(parents=True)
    (d / "session.json").write_text("{}")
    for n in range(frames):
        (d / "frames" / f"{n:06d}.jpg").write_bytes(b"j" * (MB // 4))
        (d / "frames" / f"{n:06d}.json").write_text("{}")
    for n in range(previews):
        (d / "preview" / f"v{n:05d}.dpg").write_bytes(b"p" * 1000)
    if previews:
        (d / "preview" / "latest.json").write_text("{}")
    if model:
        (d / "final" / "model.glb").write_bytes(b"glTF" * 1000)
        (d / "final" / "manifest.json").write_text("{}")
        (d / "final" / "report.json").write_text("{}")
    elif frames:
        (d / "final" / "manifest.json").write_text("{}")     # a final step that built nothing leaves this behind
    when = time.time() - age_days * DAY
    for root, dirs, files in os.walk(d):
        for name in dirs + files:
            os.utime(os.path.join(root, name), (when, when))
    os.utime(d, (when, when))
    return d


def files(d):
    return sorted(str(p.relative_to(d)).replace(os.sep, "/") for p in d.rglob("*") if p.is_file())


@pytest.fixture
def data(tmp_path):
    (tmp_path / "sessions").mkdir()
    return tmp_path


def test_nothing_is_removed_without_apply(data, capsys):
    old_done = make_session(data, "20260101-120000-aaaaaa", age_days=45)
    old_empty = make_session(data, "20260102-120000-bbbbbb", age_days=45, model=False)
    before = files(data)
    assert clean_sessions.main(["--data", str(data)]) == 0
    out = capsys.readouterr().out
    assert files(data) == before
    assert "20260101-120000-aaaaaa" in out and "20260102-120000-bbbbbb" in out
    assert "rien n'a été supprimé" in out and "--apply" in out
    assert old_done.exists() and old_empty.exists()


def test_apply_removes_the_views_of_old_finished_dishes_and_keeps_their_model(data, capsys):
    d = make_session(data, "20260101-120000-aaaaaa", age_days=45, frames=8)      # 8 views of 0,25 Mo
    assert clean_sessions.main(["--data", str(data), "--apply"]) == 0
    assert files(d) == ["final/manifest.json", "final/model.glb", "final/report.json", "session.json"]
    assert (d / "frames").is_dir() and (d / "preview").is_dir()      # the calculator still knows the dish
    out = capsys.readouterr().out
    assert "20260101-120000-aaaaaa" in out and "2 Mo" in out
    assert clean_sessions.main(["--data", str(data), "--apply"]) == 0      # a second pass finds nothing more
    assert "20260101-120000-aaaaaa" not in capsys.readouterr().out


def test_apply_removes_old_scans_that_never_gave_a_model(data):
    d = make_session(data, "20260102-120000-bbbbbb", age_days=45, model=False)
    assert clean_sessions.main(["--data", str(data), "--apply"]) == 0
    assert not d.exists()


def test_recent_sessions_are_never_touched(data):
    done = make_session(data, "20260101-120000-aaaaaa", age_days=10)
    empty = make_session(data, "20260102-120000-bbbbbb", age_days=10, model=False)
    # An old dish that was reopened yesterday (one new view) counts as recent.
    reopened = make_session(data, "20260103-120000-cccccc", age_days=45, model=False)
    (reopened / "frames" / "000099.json").write_text("{}")
    before = files(data)
    assert clean_sessions.main(["--data", str(data), "--apply"]) == 0
    assert files(data) == before and done.exists() and empty.exists()
    assert clean_sessions.main(["--data", str(data), "--apply", "--days", "7"]) == 0      # the person chooses the age
    assert not empty.exists() and files(done) == ["final/manifest.json", "final/model.glb", "final/report.json", "session.json"]
    assert reopened.exists()


def test_even_with_zero_days_a_scan_in_progress_is_not_touched(data):
    now = make_session(data, "20260104-120000-dddddd", age_days=0, model=False)
    old = make_session(data, "20260102-120000-bbbbbb", age_days=0.5, model=False)
    assert clean_sessions.main(["--data", str(data), "--apply", "--days", "0"]) == 0
    assert now.exists() and not old.exists()


def test_the_final_model_is_only_removed_when_asked_explicitly(data):
    d = make_session(data, "20260101-120000-aaaaaa", age_days=45)
    recent = make_session(data, "20260105-120000-eeeeee", age_days=3)
    assert clean_sessions.main(["--data", str(data), "--apply"]) == 0
    assert (d / "final" / "model.glb").exists()
    assert clean_sessions.main(["--data", str(data), "--apply", "--with-final"]) == 0
    assert not d.exists() and (recent / "final" / "model.glb").exists()


def test_a_dish_that_waits_for_its_calculation_is_never_touched(data):
    store = Store(data)
    waiting = make_session(data, "20260102-120000-bbbbbb", age_days=45, model=False)
    store.x("INSERT INTO sessions VALUES (?,?,?,?,?,?,?)", ("20260102-120000-bbbbbb", 0.0, "queued", "{}", "{}", "{}", None))
    store.add_finish_request("20260102-120000-bbbbbb", None)
    finishing = make_session(data, "20260106-120000-ffffff", age_days=45, model=False)
    store.x("INSERT INTO sessions VALUES (?,?,?,?,?,?,?)", ("20260106-120000-ffffff", 0.0, "finishing", "{}", "{}", "{}", None))
    gone = make_session(data, "20260107-120000-999999", age_days=45, model=False)
    store.x("INSERT INTO sessions VALUES (?,?,?,?,?,?,?)", ("20260107-120000-999999", 0.0, "capturing", "{}", "{}", "{}", None))
    store.db.close()
    before = files(waiting) + files(finishing)
    assert clean_sessions.main(["--data", str(data), "--apply", "--days", "1"]) == 0
    assert files(waiting) + files(finishing) == before
    assert not gone.exists()


def test_only_session_folders_are_looked_at(data):
    (data / "tls").mkdir()
    (data / "tls" / "server.key").write_text("secret")
    (data / "models").mkdir()
    (data / "models" / "depth.onnx").write_bytes(b"m" * 1000)
    (data / "sessions" / "notes.txt").write_text("mine")
    (data / "sessions" / "x").mkdir()                        # not a session id
    (data / "sessions" / "x" / "keep.txt").write_text("mine")
    old = time.time() - 400 * DAY
    for p in (data / "tls" / "server.key", data / "models" / "depth.onnx", data / "sessions" / "notes.txt", data / "sessions" / "x" / "keep.txt"):
        os.utime(p, (old, old))
    before = files(data)
    assert clean_sessions.main(["--data", str(data), "--apply", "--days", "1", "--with-final"]) == 0
    assert files(data) == before


def test_the_summary_says_how_much_room_is_made(data, capsys):
    make_session(data, "20260101-120000-aaaaaa", age_days=45, frames=8)        # 8 views of 0,25 Mo
    make_session(data, "20260102-120000-bbbbbb", age_days=45, model=False, frames=4)
    plan = clean_sessions.plan(data, days=30)
    assert [(a["session"], a["what"]) for a in plan] == [("20260101-120000-aaaaaa", "views"), ("20260102-120000-bbbbbb", "session")]
    assert 2 * MB <= plan[0]["bytes"] < 2.1 * MB and 1 * MB <= plan[1]["bytes"] < 1.1 * MB
    assert clean_sessions.main(["--data", str(data)]) == 0
    out = capsys.readouterr().out
    assert "2 scans" in out and "3 Mo" in out, out


def test_a_folder_without_any_scan_is_not_an_error(tmp_path, capsys):
    assert clean_sessions.main(["--data", str(tmp_path / "nowhere")]) == 0
    assert "Aucun" in capsys.readouterr().out
    assert not (tmp_path / "nowhere").exists(), "the tool created a folder"


def test_cleaning_next_to_a_running_calculator(calc):
    """The real server (fake calculation processes) and the tool on the same data folder, at the same time."""
    from tests.test_server_queue import start_finishing

    def age(sid, days):
        when = time.time() - days * DAY
        for root, dirs, names in os.walk(calc.data / "sessions" / sid):
            for name in dirs + names:
                os.utime(os.path.join(root, name), (when, when))

    done, p_done = start_finishing(calc)
    p_done.release()
    wait_for(lambda: calc.info(done)["ready"], what="the first dish to be ready")
    abandoned = calc.create()
    calc.put_frames(abandoned, 2)
    running, p_running = start_finishing(calc)          # a dish being calculated...
    queued = calc.create()
    calc.put_frames(queued, 2)
    assert calc.finish(queued).json()["queued"] is True   # ...and one that waits its turn
    for sid in (done, abandoned, running, queued):
        age(sid, 45)

    assert clean_sessions.main(["--data", str(calc.data), "--apply"]) == 0
    sessions = calc.data / "sessions"
    assert files(sessions / done) == ["final/manifest.json", "final/model.glb", "final/report.json", "session.json"]
    assert not (sessions / abandoned).exists()
    assert len(files(sessions / running)) >= 7 and len(files(sessions / queued)) == 5      # views and session.json: untouched

    info = calc.info(done)                               # the calculator still serves the finished dish
    assert info["ready"] is True and info["state"] == "done"
    assert calc.client.get(f"/sessions/{done}/artifacts/model.glb", headers=calc.auth).status_code == 200
    assert calc.client.get(f"/sessions/{abandoned}", headers=calc.auth).status_code == 404
    p_running.release()                                  # and the queue goes on as if nothing had happened
    p_queued = calc.finishing(queued)
    assert len(p_queued.existing) == 2
    p_queued.release()
    wait_for(lambda: calc.info(queued)["ready"], what="the waiting dish to be ready")
