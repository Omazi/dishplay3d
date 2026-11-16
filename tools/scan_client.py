"""Python client for the calculator API (used by replay and end-to-end tests).

It speaks exactly the protocol of the iOS app: pairing, session creation,
DPF1 frame upload, WebSocket events, DPG1 geometry download.
"""
from __future__ import annotations

import hashlib
import json
import ssl
import sys
import threading
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from reconstruction.preview_format import decode_geometry, encode_frame  # noqa: E402


def pinned_ssl_context(fingerprint: str) -> ssl.SSLContext:
    """TLS context that accepts only the certificate whose SHA-256(DER) == fingerprint."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # replaced by the explicit pin check in PinnedTransport
    ctx._dishplay_fp = fingerprint  # type: ignore[attr-defined]
    return ctx


class ScanClient:
    def __init__(self, base_url: str, fingerprint: str | None = None, token: str | None = None, timeout=60.0):
        self.base = base_url.rstrip("/")
        self.fp = fingerprint
        self.token = token
        verify = pinned_ssl_context(fingerprint) if (fingerprint and base_url.startswith("https")) else True
        self.http = httpx.Client(base_url=self.base, verify=verify, timeout=timeout)
        if fingerprint and base_url.startswith("https"):
            self._check_pin()

    def _check_pin(self):
        import socket
        from urllib.parse import urlparse
        u = urlparse(self.base)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((u.hostname, u.port), timeout=5) as s, ctx.wrap_socket(s) as t:
            der = t.getpeercert(binary_form=True)
        got = hashlib.sha256(der).hexdigest()
        if got != self.fp:
            raise ssl.SSLError(f"certificate pin mismatch: {got} != {self.fp}")

    def _h(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def health(self):
        return self.http.get("/health").raise_for_status().json()

    def pair(self, code: str, device="python-client"):
        r = self.http.post("/pair", json={"code": code, "device": device})
        r.raise_for_status()
        self.token = r.json()["token"]
        return self.token

    def create_session(self, box: dict, device: dict, reference_width_m=None):
        body = {"schema": "dishplay.session/1", "box": box, "device": device, "reference_width_m": reference_width_m}
        r = self.http.post("/sessions", json=body, headers=self._h())
        r.raise_for_status()
        return r.json()["session_id"]

    def put_frame(self, sid: str, meta: dict, jpeg: bytes, depth: bytes = b"", conf: bytes = b""):
        meta = dict(meta, session_id=sid)
        meta["image"] = dict(meta["image"], sha256=hashlib.sha256(jpeg).hexdigest())
        body = encode_frame(meta, jpeg, depth, conf)
        r = self.http.put(f"/sessions/{sid}/frames/{meta['frame_id']}", content=body,
                          headers={**self._h(), "Content-Type": "application/octet-stream"})
        r.raise_for_status()
        return r.json()

    def post(self, path, body=None):
        r = self.http.post(path, json=body or {}, headers=self._h())
        r.raise_for_status()
        return r.json()

    def get_json(self, path):
        return self.http.get(path, headers=self._h()).raise_for_status().json()

    def geometry(self, url: str) -> dict:
        r = self.http.get(url, headers=self._h())
        r.raise_for_status()
        return decode_geometry(r.content)

    def download(self, sid, name, dest: Path):
        r = self.http.get(f"/sessions/{sid}/artifacts/{name}", headers=self._h())
        r.raise_for_status()
        dest.write_bytes(r.content)


class EventListener(threading.Thread):
    """Collects WebSocket events in a background thread."""

    def __init__(self, base_url: str, sid: str, token: str, fingerprint: str | None = None):
        super().__init__(daemon=True)
        self.url = base_url.replace("https://", "wss://").replace("http://", "ws://") + f"/sessions/{sid}/events"
        self.token, self.fp = token, fingerprint
        self.events: list[dict] = []
        self.stop_flag = threading.Event()
        self.connected = threading.Event()

    def run(self):
        from websockets.sync.client import connect
        kw = {}
        if self.url.startswith("wss"):
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            kw["ssl"] = ctx
        with connect(self.url, additional_headers={"Authorization": f"Bearer {self.token}"}, **kw) as ws:
            if self.fp and self.url.startswith("wss"):
                der = ws.socket.getpeercert(binary_form=True)
                assert hashlib.sha256(der).hexdigest() == self.fp, "pin mismatch on websocket"
            self.connected.set()
            while not self.stop_flag.is_set():
                try:
                    msg = ws.recv(timeout=0.5)
                except TimeoutError:
                    continue
                except Exception:  # server closed (e.g. shutdown)
                    break
                ev = json.loads(msg)
                ev["_rx"] = time.time()
                self.events.append(ev)

    def of(self, kind):
        return [e for e in self.events if e.get("type") == kind]
