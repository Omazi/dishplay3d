"""End-to-end over the real network stack: TLS with pinned certificate, pairing,
session, DPF1 uploads, WebSocket events, progressive geometry BEFORE finish,
finishing, artifacts. The 'phone' is tools/scan_client.py speaking the iOS protocol."""
import json
import os
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
        if geo and geo[-1]["header"].get("integrated_frames", 0) >= 50:
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
    assert {f["frame_id"] for f in frames if f["status"] == "integrated"} >= set(range(5, 50))
    intervals = np.diff([x["_rx"] for x in geo])
    stats = {"first_geometry_s": first, "updates_during_capture": len(during), "interval_median_s": float(np.median(intervals)),
             "interval_p95_s": float(np.percentile(intervals, 95)), "geometry_bytes_last": geo[-1].get("bytes")}
    # finish
    cl.post(f"/sessions/{sid}/finish", {"reference_width_m": 0.24})
    t0 = time.time()
    while not lis.of("artifacts") and time.time() - t0 < 600:
        assert not lis.of("error"), lis.of("error")
        time.sleep(1)
    lis.stop_flag.set()
    art = lis.of("artifacts")[0]
    for name in ("model.glb", "points.ply", "mesh.ply", "report.json", "manifest.json", "final_preview.dpg"):
        assert name in art["files"]
    cl.download(sid, "report.json", tmp_path / "report.json")
    rep = json.loads((tmp_path / "report.json").read_text())
    assert abs(rep["scale_check"]["error_pct"]) < 5.0
    with pytest.raises(httpx.HTTPStatusError):
        cl.download(sid, "../../dishplay-scan.sqlite3", tmp_path / "x")
    stats["finish_s"] = time.time() - t0
    out = Path(os.environ.get("DISHPLAY_TEST_METRICS", tmp_path / "metrics.json"))
    out.write_text(json.dumps(stats, indent=1))
    print("E2E", stats)
