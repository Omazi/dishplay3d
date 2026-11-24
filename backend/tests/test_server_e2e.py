"""End-to-end over the real network stack: TLS with pinned certificate, pairing,
session, DPF1 uploads, WebSocket events, progressive geometry BEFORE finish,
finishing, artifacts. The 'phone' is tools/scan_client.py speaking the iOS protocol."""
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import cv2
import httpx
import numpy as np
import pytest

from app.tls import fingerprint
from scan_client import EventListener, ScanClient
from tests.helpers import box_json
from tests.synthetic import SyntheticScene, frame_meta, orbit_poses

BACKEND = Path(__file__).resolve().parents[1]


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    port = free_port()
    log = open(data / "server.log", "w")
    proc = subprocess.Popen([sys.executable, "-m", "app.main", "--data", str(data), "--port", str(port), "--host", "127.0.0.1",
                             "--code", "424242"], cwd=BACKEND, stdout=log, stderr=subprocess.STDOUT)
    url = f"https://127.0.0.1:{port}"
    for _ in range(120):
        if (data / "tls" / "server.crt").exists():
            try:
                ScanClient(url, fingerprint(data / "tls" / "server.crt")).health()
                break
            except Exception:
                pass
        time.sleep(0.5)
    else:
        proc.kill()
        raise RuntimeError((data / "server.log").read_text())
    yield url, fingerprint(data / "tls" / "server.crt"), data
    proc.terminate()
    try:
        proc.wait(15)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail("calculator did not stop within 15 s after SIGTERM")


def test_pin_mismatch_is_refused(server):
    url, fp, _ = server
    import ssl
    with pytest.raises(ssl.SSLError):
        ScanClient(url, "0" * 64)
    with pytest.raises(httpx.ConnectError):  # normal verification refuses the self-signed certificate
        httpx.get(url + "/health")


def test_full_loop_progressive_then_finish(server, tmp_path):
    url, fp, data = server
    cl = ScanClient(url, fp)
    with pytest.raises(httpx.HTTPStatusError):
        cl.pair("000000")
    cl.pair("424242")
    noauth = ScanClient(url, fp)
    with pytest.raises(httpx.HTTPStatusError) as e:
        noauth.create_session(box_json(), {"platform": "synthetic", "model": "t"})
    assert e.value.response.status_code == 401
    sid = cl.create_session(box_json(), {"platform": "synthetic", "model": "test", "lidar_available": False, "lidar_enabled": False}, 0.24)
    lis = EventListener(url, sid, cl.token, fp)
    lis.start()
    assert lis.connected.wait(10)
    sc = SyntheticScene()
    P = orbit_poses(60)
    t_start = time.time()
    sent_at = {}
    for i, T in enumerate(P):
        img, _ = sc.render(T)
        jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()
        meta = frame_meta(sc, i, T, session_id=sid)
        r = cl.put_frame(sid, meta, jpg)
        assert r["status"] == "received"
        sent_at[i] = time.time()
        if i == 5:
            assert cl.put_frame(sid, meta, jpg)["duplicate"] is True  # idempotent retry
            with pytest.raises(httpx.HTTPStatusError) as e:
                cl.put_frame(sid, meta, jpg[:-10] + b"0123456789")
            assert e.value.response.status_code == 409
        time.sleep(0.35)  # ~3 keyframes/s like the phone scheduler
    capture_end = time.time()
    # wait for the backlog to drain
    t0 = time.time()
    while time.time() - t0 < 120:
        geo = lis.of("geometry")
        seen = {f["frame_id"] for f in lis.of("frame") if f["status"] != "waiting_partner"}
        if geo and seen >= set(range(60)):
            break
        time.sleep(0.5)
    geo = lis.of("geometry")
    during = [g for g in geo if g["_rx"] <= capture_end]
    assert len(during) >= 3, "several geometry updates must arrive WHILE frames are still being captured"
    assert any(g["header"]["kind"] == "points+mesh" for g in during), "partial mesh must appear before finish"
    first = geo[0]["_rx"] - t_start
    vers = [g["header"]["version"] for g in geo]
    assert vers == sorted(vers)
    g = cl.geometry(geo[-1]["url"])
    assert g["header"]["triangle_count"] > 500 and g["header"]["point_count"] > 3000
    frames = lis.of("frame")
    final_status = {}
    for f in frames:
        final_status[f["frame_id"]] = f["status"]
    integrated = {k for k, v in final_status.items() if v == "integrated"}
    assert len(integrated & set(range(60))) >= 0.85 * 60, final_status
    # Frames not integrated live carry an explicit status (e.g. deferred to finishing under CPU load), never silence.
    assert all(final_status.get(i) in ("integrated", "deferred", "waiting_partner", "rejected") for i in range(60))
    intervals = np.diff([x["_rx"] for x in geo])
    stats = {"first_geometry_s": first, "updates_during_capture": len(during), "interval_median_s": float(np.median(intervals)),
             "interval_p95_s": float(np.percentile(intervals, 95)), "geometry_bytes_last": geo[-1].get("bytes"),
             "statuses": {s: sum(1 for v in final_status.values() if v == s) for s in set(final_status.values())}}
    # finish
    cl.post(f"/sessions/{sid}/finish", {"reference_width_m": 0.24})
    t0 = time.time()
    # The next dish is scanned while this one is being calculated: the calculation must go on (it used to be
    # stopped without a word), and the new scan is accepted and waits for the calculator.
    r = cl.http.post("/sessions", headers=cl._h(), json={"schema": "dishplay.session/1", "box": box_json(),
                                                          "device": {"platform": "synthetic", "model": "test"}})
    assert r.status_code == 200 and r.json()["waiting"] is True, r.text
    second = r.json()["session_id"]
    jpg2 = cv2.imencode(".jpg", sc.render(P[0])[0])[1].tobytes()
    assert cl.put_frame(second, frame_meta(sc, 0, P[0], session_id=second), jpg2)["status"] == "received"
    waiting = cl.session(second)
    assert (waiting["waiting"], waiting["active"], waiting["busy_with_other"], waiting["frames"]) == (True, False, True, {"received": 1})
    assert cl.post(f"/sessions/{sid}/finish", {"reference_width_m": 0.24})["note"] == "already finishing"   # asked twice: computed once
    while not lis.of("artifacts") and time.time() - t0 < 600:
        assert not lis.of("error"), lis.of("error")
        time.sleep(1)
    lis.stop_flag.set()
    art = lis.of("artifacts")[0]
    for name in ("model.glb", "points.ply", "mesh.ply", "report.json", "manifest.json", "final_preview.dpg"):
        assert name in art["files"]
    assert len(lis.of("artifacts")) == 1 and [e["state"] for e in lis.of("status")].count("done") == 1
    info = cl.session(sid)
    assert info["ready"] is True and info["busy_with_other"] is False
    assert (info["state"], info["failed"], info["error"], info["queued"]) == ("done", False, None, False)
    # Once the calculator is free the second scan gets its live worker by itself, from the stored view.
    t1 = time.time()
    while not cl.session(second)["active"] and time.time() - t1 < 60:
        time.sleep(0.5)
    resumed = cl.session(second)
    assert (resumed["active"], resumed["waiting"], resumed["busy_with_other"]) == (True, False, False)
    assert cl.session(sid)["ready"] is True
    cl.download(sid, "report.json", tmp_path / "report.json")
    rep = json.loads((tmp_path / "report.json").read_text())
    assert abs(rep["scale_check"]["error_pct"]) < 5.0
    with pytest.raises(httpx.HTTPStatusError):
        cl.download(sid, "../../dishplay-scan.sqlite3", tmp_path / "x")
    stats["finish_s"] = time.time() - t0
    out = Path(os.environ.get("DISHPLAY_TEST_METRICS", tmp_path / "metrics.json"))
    out.write_text(json.dumps(stats, indent=1))
    print("E2E", stats)


def start_calculator(data: Path):
    """A calculator of its own, started like `python -m app.main` in a terminal of its own (its own process
    group, so that the test can press Ctrl+C in that terminal). Returns the process and its address."""
    port = free_port()
    log = open(data / "server.log", "a")
    proc = subprocess.Popen([sys.executable, "-m", "app.main", "--data", str(data), "--port", str(port), "--host", "127.0.0.1",
                             "--code", "424242"], cwd=BACKEND, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    url = f"https://127.0.0.1:{port}"
    for _ in range(120):
        if (data / "tls" / "server.crt").exists():
            try:
                ScanClient(url, fingerprint(data / "tls" / "server.crt")).health()
                return proc, url
            except Exception:
                pass
        time.sleep(0.5)
    proc.kill()
    raise RuntimeError((data / "server.log").read_text())


def calculation_processes(calculator_pid: int) -> list[int]:
    """The calculation processes of this calculator, found the way the system knows them (Linux)."""
    found = []
    for task in Path(f"/proc/{calculator_pid}/task").iterdir():
        for pid in (task / "children").read_text().split():
            try:
                command = Path(f"/proc/{pid}/cmdline").read_bytes()
            except OSError:
                continue
            if b"spawn_main" in command:      # multiprocessing's "spawn" start (its resource tracker is another child)
                found.append(int(pid))
    return found


def wait_until(cond, timeout, what):
    t0 = time.time()
    while not cond():
        assert time.time() - t0 < timeout, f"timed out after {timeout} s waiting for {what}"
        time.sleep(0.2)


@pytest.mark.skipif(not Path("/proc/self/task").exists(), reason="finds the calculation process through /proc (Linux)")
def test_a_killed_calculation_is_reported_and_a_stopped_calculator_takes_its_calculation_up_again(tmp_path):
    """Real processes, real signals. (1) The final calculation is killed the way the system kills a process
    that takes too much memory: the dish is marked as failed instead of staying 'in calculation' for ever,
    and asking again starts a new process from the stored views. (2) Ctrl+C in the calculator's terminal
    during that calculation: at the next start the calculator takes it up again by itself and delivers."""
    data = tmp_path / "data"
    data.mkdir()
    proc, url = start_calculator(data)
    try:
        fp = fingerprint(data / "tls" / "server.crt")
        cl = ScanClient(url, fp)
        cl.pair("424242")
        sid = cl.create_session(box_json(), {"platform": "synthetic", "model": "test", "lidar_available": False, "lidar_enabled": False}, 0.24)
        lis = EventListener(url, sid, cl.token, fp)
        lis.start()
        assert lis.connected.wait(10)
        sc = SyntheticScene()
        for i, T in enumerate(orbit_poses(60)[:24]):
            jpg = cv2.imencode(".jpg", sc.render(T)[0], [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()
            assert cl.put_frame(sid, frame_meta(sc, i, T, session_id=sid), jpg)["status"] == "received"

        def states():
            return [e["state"] for e in lis.of("status")]
        # (1) killed
        assert cl.post(f"/sessions/{sid}/finish")["queued"] is False
        wait_until(lambda: "finishing" in states(), 30, "the final calculation to start")
        pids = calculation_processes(proc.pid)
        assert len(pids) == 1, "one calculation process at a time"
        os.kill(pids[0], signal.SIGKILL)
        wait_until(lambda: "failed" in states(), 30, "the calculator to notice that its process is gone")
        failed = [e for e in lis.of("status") if e["state"] == "failed"][-1]
        info = cl.session(sid)
        assert (info["state"], info["failed"], info["active"], info["ready"], info["busy_with_other"]) == ("failed", True, False, False, False)
        assert info["error"] == failed["error"] and "relancer" in info["error"]
        assert [e["code"] for e in lis.of("error")] == ["worker_died"]      # the event the published app shows
        assert sid in (data / "calculateur.log").read_text(encoding="utf-8")
        console = [line for line in (data / "server.log").read_text(encoding="utf-8", errors="replace").splitlines()
                   if sid in line and "[calcul]" in line]
        assert len(console) == 1 and "CHEC du calcul final" in console[0], console
        assert calculation_processes(proc.pid) == []
        # asked again ("Terminer ce plat"): the session has no process any more
        again = cl.post(f"/sessions/{sid}/finish")
        assert (again["ok"], again["queued"], again["position"]) == (True, False, 0)
        wait_until(lambda: cl.session(sid)["state"] == "finishing" and cl.session(sid)["active"], 60, "the second calculation to start")
        assert cl.session(sid)["failed"] is False
        # (2) Ctrl+C in the terminal: every process of the terminal receives it, the calculation process too
        os.killpg(proc.pid, signal.SIGINT)
        proc.wait(30)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
    lis.stop_flag.set()
    first_run = (data / "server.log").read_text(encoding="utf-8", errors="replace")
    assert first_run.count("CHEC du calcul final") == 1, "stopping the calculator was reported as a failed calculation"

    proc, url = start_calculator(data)      # the next day: same data, same certificate, same paired phone
    try:
        assert fingerprint(data / "tls" / "server.crt") == fp, "the phone would have to be paired again"
        cl = ScanClient(url, fp, token=cl.token)
        info = cl.session(sid)
        assert info["failed"] is False and info["state"] in ("queued", "finishing"), info["state"]
        assert sid in (data / "server.log").read_text(encoding="utf-8", errors="replace").split("Reprise des calculs")[-1].splitlines()[0]
        wait_until(lambda: cl.session(sid)["ready"], 600, "the model of the calculation taken up again")
        info = cl.session(sid)
        assert (info["state"], info["failed"], info["error"]) == ("done", False, None)
        assert sum(info["frames"].values()) == 24
        assert "model.glb" in cl.get_json(f"/sessions/{sid}/artifacts")["files"]
    finally:
        proc.terminate()
        try:
            proc.wait(15)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            pytest.fail("calculator did not stop within 15 s after SIGTERM")
