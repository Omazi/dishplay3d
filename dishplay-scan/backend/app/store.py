"""Session folders + SQLite index. Only the HTTP process writes the database."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, created_at REAL, state TEXT, box TEXT, device TEXT, settings TEXT, reference_width_m REAL
);
CREATE TABLE IF NOT EXISTS frames (
  session_id TEXT, frame_id INTEGER, epoch INTEGER, sha256 TEXT, received_at REAL, status TEXT, reason TEXT,
  has_depth INTEGER, bytes INTEGER, PRIMARY KEY (session_id, frame_id)
);
CREATE TABLE IF NOT EXISTS tokens (token TEXT PRIMARY KEY, device TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS events (session_id TEXT, t REAL, type TEXT, body TEXT);
"""

SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{6,64}$")


class Store:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir)
        (self.root / "sessions").mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "dishplay-scan.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.lock = threading.Lock()

    def session_dir(self, sid: str) -> Path:
        if not SESSION_ID.match(sid):
            raise ValueError("invalid session id")
        return self.root / "sessions" / sid

    def x(self, sql: str, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur.fetchall()

    # sessions
    def create_session(self, sid, box, device, settings, reference_width_m):
        d = self.session_dir(sid)
        for sub in ("frames", "preview", "final"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        (d / "session.json").write_text(json.dumps({"id": sid, "box": box, "device": device, "settings": settings,
                                                    "reference_width_m": reference_width_m, "created_at": time.time()}, indent=1))
        self.x("INSERT INTO sessions VALUES (?,?,?,?,?,?,?)", (sid, time.time(), "capturing", json.dumps(box), json.dumps(device),
                                                              json.dumps(settings), reference_width_m))

    def session(self, sid):
        rows = self.x("SELECT id, created_at, state, box, device, settings, reference_width_m FROM sessions WHERE id=?", (sid,))
        if not rows:
            return None
        r = rows[0]
        return {"id": r[0], "created_at": r[1], "state": r[2], "box": json.loads(r[3]), "device": json.loads(r[4]),
                "settings": json.loads(r[5]), "reference_width_m": r[6]}

    def set_state(self, sid, state):
        self.x("UPDATE sessions SET state=? WHERE id=?", (state, sid))

    def update_box(self, sid, box):
        self.x("UPDATE sessions SET box=? WHERE id=?", (json.dumps(box), sid))

    # frames
    def frame(self, sid, fid):
        rows = self.x("SELECT sha256, status FROM frames WHERE session_id=? AND frame_id=?", (sid, fid))
        return rows[0] if rows else None

    def add_frame(self, sid, fid, epoch, sha, has_depth, nbytes):
        self.x("INSERT INTO frames VALUES (?,?,?,?,?,?,?,?,?)", (sid, fid, epoch, sha, time.time(), "received", "", int(has_depth), nbytes))

    def frame_status(self, sid, fid, status, reason):
        self.x("UPDATE frames SET status=?, reason=? WHERE session_id=? AND frame_id=?", (status, reason, sid, fid))

    def frames(self, sid):
        return self.x("SELECT frame_id, epoch, sha256, received_at, status, reason FROM frames WHERE session_id=? ORDER BY frame_id", (sid,))

    def log_event(self, sid, ev):
        self.x("INSERT INTO events VALUES (?,?,?,?)", (sid, time.time(), ev.get("type", ""), json.dumps(ev)[:20000]))

    # tokens
    def add_token(self, token, device):
        self.x("INSERT INTO tokens VALUES (?,?,?)", (token, device, time.time()))

    def token_ok(self, token) -> bool:
        return bool(token) and bool(self.x("SELECT 1 FROM tokens WHERE token=?", (token,)))
