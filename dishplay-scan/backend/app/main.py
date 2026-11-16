"""DishPlay Scan local calculator: HTTP + WebSocket API.

Run:  python -m app.main            (HTTPS with pinned self-signed certificate)
      python -m app.main --insecure-http   (local tests only; the iOS app refuses it)
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import multiprocessing as mp
import os
import platform
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.store import Store  # noqa: E402
from reconstruction.engine import ENGINE_VERSION  # noqa: E402
from reconstruction.preview_format import EnvelopeError, decode_frame  # noqa: E402

API_VERSION = 1
CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
MAX_BODY = 20 * 1024 * 1024


def lan_addresses() -> list[str]:
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))  # no packet is sent (UDP connect only selects a route)
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(i for i in ips if not i.startswith("127."))


class Validator:
    def __init__(self):
        import jsonschema
        schema = json.loads((CONTRACTS / "capture-session.schema.json").read_text())
        self._frame = jsonschema.Draft202012Validator({**schema, "$ref": "#/$defs/frame"})
        self._session = jsonschema.Draft202012Validator({**schema, "$ref": "#/$defs/session_create"})
        self._box = jsonschema.Draft202012Validator({**schema, "$ref": "#/$defs/box"})

    @staticmethod
    def _check(v, obj):
        errs = sorted(v.iter_errors(obj), key=lambda e: e.path)
        if errs:
            e = errs[0]
            raise HTTPException(422, f"contract violation at {'/'.join(map(str, e.path)) or '<root>'}: {e.message[:200]}")

    def frame(self, o):
        self._check(self._frame, o)

    def session(self, o):
        self._check(self._session, o)

    def box(self, o):
        self._check(self._box, o)


class ActiveSession:
    def __init__(self, sid: str, proc, cmd_q):
        self.sid, self.proc, self.cmd_q = sid, proc, cmd_q
        self.sockets: set[WebSocket] = set()
        self.last_geometry: dict | None = None
        self.last_status: dict | None = None
        self.state = "capturing"


class Server:
    def __init__(self, data_dir: Path, pairing_code: str | None = None, fingerprint: str = "", base_urls=()):
        self.store = Store(data_dir)
        self.validator = Validator()
        self.ctx = mp.get_context("spawn")
        self.evt_q = self.ctx.Queue()
        self.active: ActiveSession | None = None
        self.pairing_code = pairing_code or f"{secrets.randbelow(10**6):06d}"
        self.pair_failures = 0
        self.fingerprint = fingerprint
        self.base_urls = list(base_urls)
        self.loop: asyncio.AbstractEventLoop | None = None
        self._pump = threading.Thread(target=self._pump_events, daemon=True)
        self._pump.start()

    # ------------------------------------------------------------ worker I/O
    def start_worker(self, sid: str, box: dict, settings: dict, resume=False):
        if self.active:
            self.stop_worker()
        existing = []
        if resume:
            d = self.store.session_dir(sid) / "frames"
            existing = [(str(d / f"{fid:06d}.json"), rec) for fid, _, _, rec, _, _ in self.store.frames(sid)]
        cmd_q = self.ctx.Queue()
        from app.worker import worker_main
        proc = self.ctx.Process(target=worker_main, args=(cmd_q, self.evt_q, str(self.store.session_dir(sid)), box, settings, existing),
                                daemon=True, name=f"recon-{sid}")
        proc.start()
        self.active = ActiveSession(sid, proc, cmd_q)

    def stop_worker(self):
        a = self.active
        if a is None:
            return
        a.cmd_q.put(("stop",))
        a.proc.join(timeout=3)
        if a.proc.is_alive():
            a.proc.terminate()
        self.active = None

    def _pump_events(self):
        while True:
            ev = self.evt_q.get()
            sid = ev.get("session_id")
            try:
                if ev["type"] == "frame":
                    self.store.frame_status(sid, ev["frame_id"], ev["status"], ev.get("reason", ""))
                elif ev["type"] == "status":
                    self.store.set_state(sid, ev["state"])
                if ev["type"] in ("geometry", "artifacts", "error", "status"):
                    self.store.log_event(sid, ev)
            except Exception:
                pass
            a = self.active
            if a and a.sid == sid:
                if ev["type"] == "geometry":
                    a.last_geometry = ev
                if ev["type"] == "status":
                    a.last_status, a.state = ev, ev["state"]
                if self.loop:
                    asyncio.run_coroutine_threadsafe(self._broadcast(a, ev), self.loop)

    async def _broadcast(self, a: ActiveSession, ev: dict):
        dead = []
        msg = json.dumps(ev, default=float)
        for ws in list(a.sockets):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            a.sockets.discard(ws)


def create_app(server: Server) -> FastAPI:
    app = FastAPI(title="DishPlay Scan calculator", version=ENGINE_VERSION)

    @app.on_event("startup")
    async def _startup():
        server.loop = asyncio.get_running_loop()

    @app.on_event("shutdown")
    async def _shutdown():
        server.stop_worker()

    def auth(authorization: str | None = Header(default=None)):
        token = (authorization or "").removeprefix("Bearer ").strip()
        if not server.store.token_ok(token):
            raise HTTPException(401, "missing or invalid token: pair the app first")
        return token

    def require_session(sid: str):
        s = server.store.session(sid) if len(sid) <= 64 else None
        if s is None:
            raise HTTPException(404, "unknown session")
        return s

    @app.get("/health")
    def health():
        return {"service": "dishplay-scan", "api": API_VERSION, "engine": ENGINE_VERSION, "time": time.time(),
                "active_session": server.active.sid if server.active else None,
                "worker_alive": bool(server.active and server.active.proc.is_alive())}

    @app.post("/pair")
    async def pair(request: Request):
        body = await request.json()
        if server.pair_failures >= 8:
            raise HTTPException(429, "too many attempts: restart the calculator to get a new code")
        if not secrets.compare_digest(str(body.get("code", "")), server.pairing_code):
            server.pair_failures += 1
            raise HTTPException(403, "wrong pairing code")
        token = secrets.token_urlsafe(32)
        server.store.add_token(token, str(body.get("device", ""))[:64])
        return {"token": token, "api": API_VERSION}

    @app.get("/diagnostics")
    def diagnostics(_=Depends(auth)):
        from app.diagnostics import capabilities
        return capabilities(str(server.store.root))

    @app.post("/sessions")
    async def create_session(request: Request, _=Depends(auth)):
        body = await request.json()
        server.validator.session(body)
        sid = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
        settings = {"use_lidar": bool(body["device"].get("lidar_enabled", False)), "texture": True}
        box = {**body["box"], "revision": 0}
        server.store.create_session(sid, box, body["device"], settings, body.get("reference_width_m"))
        server.start_worker(sid, box, settings)
        return {"session_id": sid, "events": f"/sessions/{sid}/events", "lidar_used": settings["use_lidar"]}

    @app.get("/sessions/{sid}")
    def get_session(sid: str, _=Depends(auth)):
        s = require_session(sid)
        frames = server.store.frames(sid)
        counts: dict[str, int] = {}
        for f in frames:
            counts[f[4]] = counts.get(f[4], 0) + 1
        a = server.active if server.active and server.active.sid == sid else None
        return {**s, "frames": counts, "active": a is not None, "last_geometry": a.last_geometry if a else None}

    @app.post("/sessions/{sid}/resume_worker")
    def resume_worker(sid: str, _=Depends(auth)):
        s = require_session(sid)
        server.start_worker(sid, s["box"], s["settings"], resume=True)
        return {"ok": True}

    @app.put("/sessions/{sid}/frames/{frame_id}")
    async def put_frame(sid: str, frame_id: int, request: Request, _=Depends(auth)):
        require_session(sid)
        clen = int(request.headers.get("content-length") or 0)
        if clen > MAX_BODY:
            raise HTTPException(413, "frame too large")
        body = await request.body()
        if len(body) > MAX_BODY:
            raise HTTPException(413, "frame too large")
        try:
            meta, image, depth, conf = decode_frame(body)
        except EnvelopeError as exc:
            raise HTTPException(400, f"bad envelope: {exc}")
        server.validator.frame(meta)
        if meta["frame_id"] != frame_id or meta["session_id"] != sid:
            raise HTTPException(400, "frame_id/session_id mismatch between URL and metadata")
        sha = hashlib.sha256(image).hexdigest()
        if sha != meta["image"]["sha256"]:
            raise HTTPException(400, "image checksum mismatch")
        if image[:3] != b"\xff\xd8\xff":
            raise HTTPException(400, "image is not a JPEG")
        if "depth" in meta:
            exp = meta["depth"]["width"] * meta["depth"]["height"]
            if len(depth) != 4 * exp or (conf and len(conf) != exp):
                raise HTTPException(400, "depth size does not match metadata")
        prev = server.store.frame(sid, frame_id)
        if prev:
            if prev[0] == sha:
                return {"frame_id": frame_id, "duplicate": True, "status": prev[1]}
            raise HTTPException(409, "frame_id already used with different content")
        fdir = server.store.session_dir(sid) / "frames"
        base = fdir / f"{frame_id:06d}"
        base.with_suffix(".jpg").write_bytes(image)
        if depth:
            base.with_suffix(".depth").write_bytes(depth)
        if conf:
            base.with_suffix(".conf").write_bytes(conf)
        meta_path = base.with_suffix(".json")
        meta_path.write_text(json.dumps(meta))  # written last: marks the frame complete
        server.store.add_frame(sid, frame_id, meta["epoch"], sha, bool(depth), len(body))
        received = time.time()
        a = server.active
        if a and a.sid == sid:
            a.cmd_q.put(("frame", str(meta_path), received))
        return {"frame_id": frame_id, "duplicate": False, "status": "received", "queued": bool(a and a.sid == sid)}

    @app.post("/sessions/{sid}/box")
    async def revise_box(sid: str, request: Request, _=Depends(auth)):
        s = require_session(sid)
        box = await request.json()
        server.validator.box(box)
        box["revision"] = int(s["box"].get("revision", 0)) + 1
        server.store.update_box(sid, box)
        if server.active and server.active.sid == sid:
            server.active.cmd_q.put(("box", box))
        return {"revision": box["revision"], "note": "volume rebuilt from stored frames"}

    for action in ("pause", "resume"):
        def _make(action=action):
            def handler(sid: str, _=Depends(auth)):
                require_session(sid)
                if not (server.active and server.active.sid == sid):
                    raise HTTPException(409, "session not active")
                server.active.cmd_q.put((action,))
                return {"ok": True}
            return handler
        app.post(f"/sessions/{{sid}}/{action}")(_make())

    @app.post("/sessions/{sid}/finish")
    async def finish(sid: str, request: Request, _=Depends(auth)):
        s = require_session(sid)
        if not (server.active and server.active.sid == sid):
            raise HTTPException(409, "session not active (POST /sessions/{id}/resume_worker first)")
        try:
            body = await request.json()
        except Exception:
            body = {}
        ref = body.get("reference_width_m", s.get("reference_width_m"))
        server.active.cmd_q.put(("finish", float(ref) if ref else None))
        return {"ok": True, "note": "finishing runs in the worker; follow events"}

    @app.get("/sessions/{sid}/preview/{version}")
    def preview(sid: str, version: str, _=Depends(auth)):
        d = server.store.session_dir(require_session(sid)["id"]) / "preview"
        if version == "latest":
            if not (d / "latest.json").exists():
                raise HTTPException(404, "no preview yet")
            version = str(json.loads((d / "latest.json").read_text())["version"])
        if not version.isdigit():
            raise HTTPException(400, "bad version")
        p = d / f"v{int(version):05d}.dpg"
        if not p.exists():
            raise HTTPException(404, "unknown version")
        return FileResponse(p, media_type="application/octet-stream", headers={"X-Geometry-Version": version})

    @app.get("/sessions/{sid}/artifacts")
    def artifacts(sid: str, _=Depends(auth)):
        d = server.store.session_dir(require_session(sid)["id"]) / "final"
        files = sorted(p.name for p in d.iterdir() if p.is_file()) if d.exists() else []
        return {"files": files, "ready": "manifest.json" in files}

    @app.get("/sessions/{sid}/artifacts/{name}")
    def artifact(sid: str, name: str, _=Depends(auth)):
        d = server.store.session_dir(require_session(sid)["id"]) / "final"
        allowed = {p.name for p in d.iterdir() if p.is_file()} if d.exists() else set()
        if name not in allowed:  # never build paths from user input
            raise HTTPException(404, "unknown artifact")
        return FileResponse(d / name)

    @app.websocket("/sessions/{sid}/events")
    async def events(ws: WebSocket, sid: str):
        token = (ws.headers.get("authorization") or "").removeprefix("Bearer ").strip() or ws.query_params.get("token", "")
        if not server.store.token_ok(token) or server.store.session(sid) is None:
            await ws.close(code=4401)
            return
        await ws.accept()
        a = server.active if server.active and server.active.sid == sid else None
        await ws.send_text(json.dumps({"type": "hello", "session_id": sid, "server_time": time.time(), "active": a is not None}))
        if a:
            a.sockets.add(ws)
            for ev in (a.last_status, a.last_geometry):
                if ev:
                    await ws.send_text(json.dumps(ev, default=float))
        try:
            while True:
                msg = await ws.receive_text()
                if msg == "ping":
                    await ws.send_text(json.dumps({"type": "pong", "server_time": time.time()}))
        except WebSocketDisconnect:
            pass
        finally:
            if a:
                a.sockets.discard(ws)

    @app.get("/", response_class=HTMLResponse)
    def pairing_page(request: Request):
        if request.client and request.client.host not in ("127.0.0.1", "::1", "localhost"):
            return HTMLResponse("<p>Open this page on the calculator itself.</p>", status_code=403)
        import segno
        blocks = []
        for url in server.base_urls:
            link = pairing_link(url, server.pairing_code, server.fingerprint)
            svg = segno.make(link, error="m").svg_inline(scale=5)
            blocks.append(f"<div style='display:inline-block;margin:12px;text-align:center'>{svg}<p><b>{url}</b></p></div>")
        return HTMLResponse(f"""<!doctype html><meta charset=utf-8><title>DishPlay Scan</title>
<body style="font-family:system-ui;margin:24px"><h1>DishPlay Scan – calculateur</h1>
<p>Scannez ce QR avec l'appareil photo de l'iPhone, ou saisissez l'adresse et le code dans l'app.</p>
{''.join(blocks)}<p>Code de jumelage : <b style="font-size:28px">{server.pairing_code}</b></p>
<p>Empreinte TLS (SHA-256) : <code>{server.fingerprint}</code></p></body>""")

    return app


def pairing_link(base_url: str, code: str, fp: str) -> str:
    from urllib.parse import quote
    return f"dishplayscan://pair?u={quote(base_url, safe='')}&c={code}&fp={fp}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="DishPlay Scan local calculator")
    ap.add_argument("--data", default=os.environ.get("DISHPLAY_DATA", str(Path.home() / "dishplay-scan-data")))
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--insecure-http", action="store_true", help="plain HTTP (automated tests only; the iOS app requires TLS)")
    ap.add_argument("--code", help="fixed pairing code (tests)")
    args = ap.parse_args(argv)
    import uvicorn
    data = Path(args.data)
    ips = lan_addresses()
    scheme = "http" if args.insecure_http else "https"
    ssl = {}
    fp = ""
    if not args.insecure_http:
        from app.tls import ensure_certificate
        cert, key, fp = ensure_certificate(data / "tls", ips)
        ssl = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
    urls = [f"{scheme}://{ip}:{args.port}" for ip in ips] or [f"{scheme}://127.0.0.1:{args.port}"]
    server = Server(data, args.code, fp, urls)
    print("\n=== DishPlay Scan calculator ===")
    print(f"data: {data}\npairing code: {server.pairing_code}\nTLS fingerprint: {fp or '(none: insecure HTTP)'}")
    for u in urls:
        print(f"address: {u}\n  pairing link: {pairing_link(u, server.pairing_code, fp)}")
    try:
        import segno
        if urls and not args.insecure_http:
            segno.make(pairing_link(urls[0], server.pairing_code, fp), error="m").terminal(compact=True)
    except Exception:
        pass
    print(f"QR page (open on this computer): {scheme}://127.0.0.1:{args.port}/\n")
    uvicorn.run(create_app(server), host=args.host, port=args.port, log_level="info", ws_ping_interval=10, timeout_graceful_shutdown=3, **ssl)


if __name__ == "__main__":
    mp.freeze_support()
    main()
