"""DishPlay Scan local calculator: HTTP + WebSocket API.

Run:  python -m app.main            (HTTPS with pinned self-signed certificate)
      python -m app.main --insecure-http   (local tests only; the iOS app refuses it)
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import math
import multiprocessing as mp
import os
import platform
import secrets
import shutil
import socket
import sqlite3
import sys
import queue
import threading
import time
import traceback
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.diagnostics import LOW_FREE_BYTES, MIN_FREE_BYTES, free_bytes, human_size  # noqa: E402
from app.store import Store  # noqa: E402
from app.worker import FAILURE_TEXT, failure_reason  # noqa: E402
from reconstruction.engine import ENGINE_VERSION  # noqa: E402
from reconstruction.preview_format import EnvelopeError, decode_frame  # noqa: E402

API_VERSION = 1
CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
MAX_BODY = 20 * 1024 * 1024          # one view (picture, depth, metadata)
MAX_JSON_BODY = 64 * 1024            # every other body: pairing, new session, box, finish request
PAIR_MAX_FAILURES = 8                # wrong pairing codes in a row before pairing is blocked...
PAIR_BLOCK_S = 60.0                  # ...for this long (not for ever: any device of the network can send wrong codes)
WATCH_S = 0.5            # how often the server looks at its calculation process (gone? somebody next in line?)
SHUTDOWN_WAIT_S = 3      # what the calculator gives open connections to end when it is asked to stop
DEATH_GRACE_S = 6.0      # a final calculation found dead is called a failure only after this long (see _pump_events)
STUCK_PUMP_S = 10.0      # a process that is gone, and whose event pipe cannot be read, is given up after this long
CAPTURE_GRACE_S = 30.0   # a scan that sent a view more recently than this keeps the calculator
MAX_LIVE_CRASHES = 3     # live workers of one session that may die before its views stop restarting one
STOP_WAIT_S = 3.0        # a process asked to stop is given this long before it is terminated
STORAGE_ALERT_S = 60.0   # a disk problem is told on the console of the PC at most this often

# What a phone is told (HTTP 507) when its data cannot be stored. The app shows the sentence to the person.
DISK_ALMOST_FULL = (f"Le disque du PC est presque plein (moins de {human_size(MIN_FREE_BYTES)} libres) : "
                    "libérez de la place sur le PC, l'envoi reprendra tout seul.")
DISK_FULL = "Le disque du PC est plein : libérez de la place sur le PC, l'envoi reprendra tout seul."
DISK_WRITE_FAILED = "Le PC n'a pas pu enregistrer ces données sur son disque (détails dans calculateur.log sur le PC)."


def lan_addresses() -> list[str]:
    """IPv4 addresses of this computer, the one of the default route first: with several network cards, a
    VPN or virtual adapters it is the one an iPhone on the same Wi-Fi most likely reaches."""
    first = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("192.0.2.1", 9))  # no packet is sent (UDP connect only selects a route)
            first = s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        pass
    others = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            others.add(info[4][0])
    except OSError:
        pass
    ordered = ([first] if first else []) + sorted(others - {first})
    return [i for i in ordered if not i.startswith("127.")]


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
    """The calculation process (there is only one at a time) and the session it works for."""

    def __init__(self, sid: str, proc, cmd_q, evt_q):
        self.sid, self.proc, self.cmd_q, self.evt_q = sid, proc, cmd_q, evt_q
        self.last_geometry: dict | None = None
        self.last_progress: dict | None = None   # latest finish_progress: where the final calculation stands
        self.state = "capturing"
        self.finishing = False         # the order to finish was sent and is not over (it ends after the neural step)
        self.retired = False           # stopped by the server, or dead: what it still says no longer counts
        self.last_frame_at = time.time()
        self.dead_since: float | None = None


class Server:
    """Sessions, their one calculation process, and who gets it next.

    One process at a time. A session being finished is never stopped: the finish requests of the others wait
    in `finish_queue` (first in, first out) and start by themselves, and a scan opened meanwhile waits in
    `waiting` for its live worker. Everything that decides who gets the process runs with `lock` held.
    """

    def __init__(self, data_dir: Path, pairing_code: str | None = None, fingerprint: str = "", base_urls=()):
        self.store = Store(data_dir)
        self.validator = Validator()
        self.ctx = mp.get_context("spawn")
        self.lock = threading.RLock()
        self.active: ActiveSession | None = None
        self.finish_queue: list[str] = []            # sessions whose final calculation waits its turn, oldest first
        self.waiting: list[str] = []                 # scans that wait for a live worker, most recent last
        self.restored: list[str] = []                # finish requests taken up again when the calculator started
        self.sockets: dict[str, set[WebSocket]] = {}     # phones listening, per session (not per process)
        self.last_events: dict[str, dict] = {}       # per session: the last status and geometry sent to phones
        self.crashes: dict[str, int] = {}            # per session: live workers that died
        self.log_path = self.store.root / "calculateur.log"
        self._storage_said_at = float("-inf")
        self.pairing_code = pairing_code or f"{secrets.randbelow(10**6):06d}"
        self.pair_failures = 0
        self.pair_blocked_until = 0.0                # time.monotonic() until which pairing is refused
        self.fingerprint = fingerprint
        self.base_urls = list(base_urls)
        self.loop: asyncio.AbstractEventLoop | None = None
        self._closed = threading.Event()
        self._restore_queue()
        threading.Thread(target=self._watchdog, daemon=True, name="watchdog").start()

    def close(self):
        """The calculator stops. A final calculation in progress keeps its request: it is taken up again at the next start."""
        self._closed.set()
        self.loop = None
        with self.lock:
            self.stop_worker()

    # ------------------------------------------------------------ console and log file of the PC
    def _log(self, title: str, *details: str):
        """Append to calculateur.log, in the data folder: what happened, with everything useful to understand it."""
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {title}\n")
                for d in details:
                    for line in str(d or "").rstrip().splitlines():
                        f.write(f"    {line}\n")
        except OSError:
            pass

    @staticmethod
    def _say(text: str):
        """One line on the console of the PC (a console that cannot show accents must not stop anything)."""
        try:
            print(text, flush=True)
        except Exception:
            try:
                print(text.encode("ascii", "replace").decode(), flush=True)
            except Exception:
                pass

    def pair_blocked_for(self) -> float:
        """Seconds during which pairing is still refused (0: it is open)."""
        return max(0.0, self.pair_blocked_until - time.monotonic())

    def pair_failed(self):
        """One more wrong pairing code. After PAIR_MAX_FAILURES in a row pairing is closed for PAIR_BLOCK_S;
        what is tried meanwhile is refused without making the block longer."""
        self.pair_failures += 1
        if self.pair_failures >= PAIR_MAX_FAILURES:
            self.pair_failures = 0
            self.pair_blocked_until = time.monotonic() + PAIR_BLOCK_S
            text = f"{PAIR_MAX_FAILURES} codes de jumelage faux de suite : le jumelage est bloqué pendant {PAIR_BLOCK_S:g} s."
            self._say(f"[jumelage] {text}")
            self._log(text)

    def storage_refusal(self, exc: BaseException | None = None) -> HTTPException:
        """The answer to a phone whose data cannot be stored: HTTP 507 and one French sentence, instead of an
        error 500 without a word. exc: the write that failed (None: refused beforehand, too little free space).
        The person at the PC is told as well, and the log, at most once every STORAGE_ALERT_S."""
        if exc is None:
            sentence = DISK_ALMOST_FULL
        else:
            sentence = DISK_FULL if failure_reason(exc) == "disk_full" else DISK_WRITE_FAILED
        if time.monotonic() - self._storage_said_at > STORAGE_ALERT_S:
            self._storage_said_at = time.monotonic()
            self._say(f"[disque] {sentence.split(' : ')[0].rstrip('.')}. Dossier des données : {self.store.root}. "
                      "Pour supprimer les anciens scans : outil tools/clean_sessions.py")
            self._log(f"Données refusées (réponse 507) : {sentence}", repr(exc) if exc is not None else "")
        return HTTPException(507, sentence)

    # ------------------------------------------------------------ the calculation process
    def start_worker(self, sid: str, resume=False) -> ActiveSession:
        """Replace the calculation process by one for this session (never called while a dish is being finished).
        resume: the process first takes over the views already stored."""
        s = self.store.session(sid)
        self.stop_worker()
        existing = []
        if resume:
            d = self.store.session_dir(sid) / "frames"
            existing = [(str(d / f"{fid:06d}.json"), rec) for fid, _, _, rec, _, _ in self.store.frames(sid)
                        if (d / f"{fid:06d}.json").exists()]
        cmd_q, evt_q = self.ctx.Queue(), self.ctx.Queue()
        from app.worker import worker_main
        proc = self.ctx.Process(target=worker_main, args=(cmd_q, evt_q, str(self.store.session_dir(sid)), s["box"], s["settings"], existing),
                                daemon=True, name=f"recon-{sid}")
        proc.start()
        a = ActiveSession(sid, proc, cmd_q, evt_q)
        self.active = a
        if sid in self.waiting:
            self.waiting.remove(sid)
        threading.Thread(target=self._pump_events, args=(a,), daemon=True, name=f"events-{sid}").start()
        return a

    def stop_worker(self):
        a = self.active
        if a is None:
            return
        self.active = None
        a.retired = True
        if a.proc.is_alive():
            a.cmd_q.put(("stop",))
            a.proc.join(timeout=STOP_WAIT_S)
            if a.proc.is_alive():
                a.proc.terminate()

    def _pump_events(self, a: ActiveSession):
        """Read what one process says, until it is stopped. Each process has its own pipe and its own reader:
        a process killed in the middle of a message cannot spoil the events of the next one. This reader is
        also the first to notice that its process died without a word."""
        while True:
            try:
                ev = a.evt_q.get(timeout=WATCH_S)
            except queue.Empty:
                if a.retired:
                    return
                if a.proc.is_alive():
                    continue
                while True:          # gone: what it wrote before going is handled first
                    try:
                        ev = a.evt_q.get_nowait()
                    except Exception:
                        break
                    self._on_event(a, ev)
                if a.finishing:
                    # Closing the calculator's window, or Ctrl+C in it, can end this process a moment before
                    # the calculator itself (which first gives its connections SHUTDOWN_WAIT_S to end). That is
                    # a stop, and the calculation is taken up again at the next start, not a failed dish:
                    # nothing is concluded, and nothing written, before the calculator had time to stop too.
                    self._closed.wait(DEATH_GRACE_S)
                with self.lock:
                    self._worker_died(a)
                return
            except Exception:        # the pipe of a killed process can be unreadable: the watchdog concludes
                if a.retired:
                    return
                time.sleep(WATCH_S)
                continue
            self._on_event(a, ev)

    def _on_event(self, a: ActiveSession, ev: dict):
        try:
            with self.lock:
                if a.retired or a is not self.active:
                    return
                kind, sid = ev.get("type"), a.sid
                if kind == "finish_over":            # internal: the whole finish command is over
                    a.finishing = False
                    if ev.get("ok"):
                        self.store.end_finish_request(sid)
                    else:
                        self._fail(sid, ev.get("reason") or "exception", ev.get("detail"), ev.get("trace"))
                    self._schedule()
                    return
                if kind == "frame":
                    self.store.frame_status(sid, ev["frame_id"], ev["status"], ev.get("reason", ""))
                elif kind == "status":
                    if a.finishing and ev["state"] in ("capturing", "paused"):
                        return   # said before the process read the order to finish: the dish did not go back to capture
                    a.state = ev["state"]
                    self.store.set_state(sid, ev["state"])
                    if a.finishing and ev["state"] == "done":
                        # The model is delivered: whatever happens in the optional step that may follow, a
                        # calculator that restarts must not calculate this dish again.
                        self.store.end_finish_request(sid)
                elif kind == "geometry":
                    a.last_geometry = ev
                elif kind == "finish_progress":
                    a.last_progress = {k: ev.get(k) for k in ("step", "done", "total")}
                self._publish(sid, ev, log=kind in ("geometry", "artifacts", "error", "status"))
        except Exception:
            self._log("Événement du calcul non traité", repr(ev)[:500], traceback.format_exc())

    def _watchdog(self):
        """Every WATCH_S: give its turn to whoever waits for a scan to go quiet, and conclude about a dead
        process whose reader is stuck on an unreadable pipe."""
        while not self._closed.wait(WATCH_S):
            try:
                with self.lock:
                    a = self.active
                    if a is not None and not a.proc.is_alive():
                        a.dead_since = a.dead_since or time.monotonic()
                        if time.monotonic() - a.dead_since > STUCK_PUMP_S:
                            self._worker_died(a)
                    if self.finish_queue or self.waiting:
                        self._schedule()
            except Exception:
                self._log("Erreur de surveillance du calcul", traceback.format_exc())

    def _worker_died(self, a: ActiveSession):
        """The process of `a` is gone without having been asked to. Called with the lock held."""
        if a.retired or a is not self.active or self._closed.is_set():
            return
        self.active = None
        a.retired = True
        detail = f"processus terminé sans prévenir (code de sortie {getattr(a.proc, 'exitcode', None)})"
        if a.finishing and a.state != "done":
            # App 1.7.0 only shows "error" events; the "failed" status that follows is for the versions after it.
            self._publish(a.sid, {"type": "error", "code": "worker_died", "message": FAILURE_TEXT["died"]})
            self._fail(a.sid, "died", detail)
        elif a.finishing:            # it died in the optional step, after the model was delivered: the dish is fine
            self.store.end_finish_request(a.sid)
            self._log(f"Plat {a.sid} : modèle livré, mais l'étape facultative qui suivait s'est arrêtée", detail)
        elif a.state == "done":      # it had nothing left to do for this dish: nobody needs to be alarmed
            self._log(f"Plat {a.sid} : le processus resté en attente après la livraison du modèle s'est arrêté", detail)
        else:
            self.crashes[a.sid] = self.crashes.get(a.sid, 0) + 1
            text = "Le calcul en direct de ce scan s'est arrêté sur le PC ; il reprendra à la prochaine vue reçue."
            self._publish(a.sid, {"type": "error", "code": "worker_died", "message": text})
            self._log(f"Plat {a.sid} : {text}", detail)
            self._say(f"[calcul] Plat {a.sid} : {text}")
        self._schedule()

    def _fail(self, sid: str, reason: str, detail: str | None = None, trace: str | None = None):
        """The final calculation of this session ended without a model: the session is marked as failed (and
        stays so until a new finish request), the phones and the person at the PC are told, the details go to
        calculateur.log. Called with the lock held; the caller then lets the queue move on."""
        sentence = FAILURE_TEXT.get(reason, FAILURE_TEXT["exception"])
        a = self.active
        if a is not None and a.sid == sid:
            self.stop_worker()       # in an unknown state, and possibly holding a lot of memory: not kept
        if sid in self.finish_queue:
            self.finish_queue.remove(sid)
        self.store.end_finish_request(sid)
        self.store.set_failure(sid, sentence)        # before the state: whoever reads "failed" finds the reason
        self.store.set_state(sid, "failed")
        self._publish(sid, {"type": "status", "state": "failed", "error": sentence})
        self._log(f"Plat {sid} : ÉCHEC du calcul final ({reason}). {sentence}", detail, trace)
        self._say(f"[calcul] Plat {sid} : ÉCHEC du calcul final. {sentence} Journal : {self.log_path}")

    # ------------------------------------------------------------ what the phones receive
    def _publish(self, sid: str, ev: dict, log=True):
        """One event of a session: remembered (status, geometry), stored, and sent to the phones listening to it."""
        ev.setdefault("session_id", sid)
        if log:
            try:
                self.store.log_event(sid, ev)
            except Exception:
                pass
        if ev.get("type") in ("status", "geometry"):
            self.last_events.setdefault(sid, {})[ev["type"]] = ev
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        coro = self._broadcast(sid, ev)
        try:
            asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:         # the calculator is stopping
            coro.close()

    async def _broadcast(self, sid: str, ev: dict):
        msg = json.dumps(ev, default=float)
        listeners = self.sockets.get(sid, set())
        for ws in list(listeners):
            try:
                await ws.send_text(msg)
            except Exception:
                listeners.discard(ws)

    def last_status(self, sid: str) -> dict | None:
        """The last status sent for this session; when the calculator has said nothing yet since it started,
        what it had written down (a dish that failed or waits is told at once to the phone that connects)."""
        ev = self.last_events.get(sid, {}).get("status")
        if ev is None and (s := self.store.session(sid)) is not None:
            ev = {"type": "status", "session_id": sid, "state": s["state"]}
            if s["state"] == "failed":
                ev["error"] = self.store.failure(sid)
        return ev

    # ------------------------------------------------------------ who gets the calculator
    def _restore_queue(self):
        """Final calculations that were running or waiting when the calculator stopped get their turn again,
        in the same order. Once: a calculation already taken up after a first stop, and interrupted again, is
        marked as failed instead (a calculation that brings the computer down must not do it at every start)."""
        with self.lock:
            for sid, started, restarts in self.store.finish_requests():
                s = self.store.session(sid)
                if s is None or s["state"] == "failed" or not self.store.session_dir(sid).is_dir():
                    self.store.end_finish_request(sid)
                elif started and restarts >= 1:
                    self._fail(sid, "interrupted_twice")
                else:
                    if started:
                        self.store.requeue_finish_request(sid)
                    self.finish_queue.append(sid)
                    self.store.set_state(sid, "queued")
                    self.restored.append(sid)
            self._schedule()

    def _preemptable(self) -> bool:
        """May the calculation process be given to another session? Never while it finishes a dish; not while
        it follows a scan that sent a view in the last CAPTURE_GRACE_S seconds."""
        a = self.active
        if a is None or not a.proc.is_alive():
            return a is None or not a.finishing
        if a.finishing:
            return False
        if a.state in ("done", "failed") or a.sid in self.finish_queue:
            return True          # nothing left to follow: delivered, or its own final calculation waits its turn
        return time.time() - a.last_frame_at > CAPTURE_GRACE_S

    def _schedule(self):
        """Give the calculator to the next in line: the oldest finish request, else the most recent scan that
        waits for its live worker. Called with the lock held, whenever something may have changed."""
        if self._closed.is_set():
            return
        a = self.active
        if a is not None and not a.finishing and not a.proc.is_alive():
            self._worker_died(a)     # (calls back here)
            return
        if a is not None and a.finishing:
            return                   # only the end of its command, or its death, frees the calculator
        while self.finish_queue:
            sid = self.finish_queue[0]
            a = self.active
            if a is not None and a.sid != sid and not self._preemptable():
                return
            self.finish_queue.pop(0)
            if self._begin_finish(sid):
                for n, waiting in enumerate(self.finish_queue):
                    self._publish(waiting, {"type": "status", "state": "queued", "queue_position": n + 1}, log=False)
                return
        if self.waiting and self._preemptable():
            sid = self.waiting[-1]
            self.waiting.clear()
            try:
                self.start_worker(sid, resume=True)
            except Exception:
                self._log(f"Plat {sid} : le calcul en direct n'a pas pu démarrer", traceback.format_exc())

    def _begin_finish(self, sid: str) -> bool:
        """Start the final calculation of this session now (its own process, started in resume mode when it has
        none). False when it could not be started: the caller goes on with the next request."""
        s, req = self.store.session(sid), self.store.finish_request(sid)
        if s is None or req is None:
            self.store.end_finish_request(sid)
            return False
        a = self.active
        try:
            if a is None or a.sid != sid or not a.proc.is_alive():
                a = self.start_worker(sid, resume=True)
        except Exception as exc:
            self._fail(sid, "start", repr(exc), traceback.format_exc())
            return False
        a.finishing, a.state, a.last_progress = True, "finishing", None
        a.cmd_q.put(("finish", req[0]))
        self.store.start_finish_request(sid)
        self.store.set_state(sid, "finishing")
        self.store.clear_failure(sid)
        self._publish(sid, {"type": "status", "state": "finishing", "queue": 0})
        return True

    def request_finish(self, sid: str, reference_width_m: float | None) -> dict:
        """The person asks for the final model of this session: now if the calculator is free, else in its turn."""
        with self.lock:
            a = self.active
            if a is not None and a.sid == sid and a.finishing:
                return {"ok": True, "queued": False, "position": 0, "note": "already finishing"}
            if sid in self.finish_queue:
                return {"ok": True, "queued": True, "position": self.finish_queue.index(sid) + 1, "note": "already queued"}
            self.store.add_finish_request(sid, reference_width_m)
            self.finish_queue.append(sid)
            if sid in self.waiting:
                self.waiting.remove(sid)
            self._schedule()
            if sid in self.finish_queue:
                position = self.finish_queue.index(sid) + 1
                self.store.set_state(sid, "queued")
                self.store.clear_failure(sid)        # a dish that failed gets a new chance
                self._publish(sid, {"type": "status", "state": "queued", "queue_position": position})
                return {"ok": True, "queued": True, "position": position}
            return {"ok": True, "queued": False, "position": 0, "note": "finishing runs in the worker; follow events"}

    def open_session(self, sid: str, created=False) -> str:
        """Give this session its live worker, now or as soon as the calculator is free.
        Returns "active" (it has one), "started", "queued" (its final calculation waits its turn) or "waiting"."""
        with self.lock:
            self._schedule()
            a = self.active
            if a is not None and a.sid == sid and a.proc.is_alive():
                return "active"
            if sid in self.finish_queue:
                return "queued"
            busy = bool(self.finish_queue) or (a is not None and a.finishing)
            # A scan just started takes the calculator from an older scan, as it always did; a dish that is
            # reopened does not take it from a scan that is still sending views.
            if not busy and (created or self._preemptable()):
                self.start_worker(sid, resume=not created)
                return "started"
            if sid in self.waiting:
                self.waiting.remove(sid)
            self.waiting.append(sid)
            return "waiting"

    def frame_stored(self, sid: str, meta_path: str, received: float) -> bool:
        """A view was written to disk: hand it to the worker of its session. A session without worker gets one
        when the calculator is free (this is what lets a scan go on after a restart of the calculator); else
        the view simply waits on disk. True when a worker has the view."""
        with self.lock:
            self._schedule()
            a = self.active
            if a is not None and a.sid == sid and a.proc.is_alive():
                a.cmd_q.put(("frame", meta_path, received))
                a.last_frame_at = received
                return True
            if sid in self.finish_queue:
                return False         # read with the others when its final calculation starts
            if self.finish_queue or (a is not None and a.finishing):
                if sid in self.waiting:
                    self.waiting.remove(sid)
                self.waiting.append(sid)     # this scan is still going on: it is the first to get a live worker again
                return False
            if self.crashes.get(sid, 0) >= MAX_LIVE_CRASHES or not self._preemptable():
                return False
            try:
                self.start_worker(sid, resume=True)      # takes over every stored view, this one included
            except Exception:
                self._log(f"Plat {sid} : le calcul en direct n'a pas pu démarrer", traceback.format_exc())
                return False
            return True


def final_summary(final_dir: Path) -> tuple[dict | None, list]:
    """Verdict and fallbacks of a final model, as written by the engine in final/report.json (None and [] when
    there is no report, or a report from an engine that did not give them yet)."""
    try:
        rep = json.loads((final_dir / "report.json").read_text())
        return rep.get("verdict"), rep.get("fallbacks") or []
    except (OSError, ValueError, AttributeError):
        return None, []


async def read_body(request: Request, limit: int, too_large: str = "request body too large") -> bytes:
    """The body of a request, refused (413) as soon as it exceeds `limit`, whether or not its size was announced."""
    try:
        announced = int(request.headers.get("content-length") or 0)
    except ValueError:
        announced = 0
    if announced > limit:
        raise HTTPException(413, too_large)
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, too_large)
        chunks.append(chunk)
    return b"".join(chunks)


async def read_json(request: Request) -> dict:
    """The small JSON object every route but the upload of a view expects (400 or 422 when it is something else)."""
    raw = await read_body(request, MAX_JSON_BODY)
    try:
        body = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "body is not valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(422, "body must be a JSON object")
    return body


def create_app(server: Server) -> FastAPI:
    # No /docs, /redoc or /openapi.json: they described the whole API to any device of the network, without token.
    @contextlib.asynccontextmanager
    async def lifespan(_app):
        server.loop = asyncio.get_running_loop()
        yield
        server.close()

    app = FastAPI(title="DishPlay Scan calculator", version=ENGINE_VERSION, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    def auth(authorization: str | None = Header(default=None)):
        token = (authorization or "").removeprefix("Bearer ").strip()
        if not server.store.token_ok(token):
            raise HTTPException(401, "missing or invalid token: pair the app first")
        return token

    def known_session(sid: str):
        """The session, or None. A session whose folder was removed (tools/clean_sessions.py) is no longer known."""
        s = server.store.session(sid) if len(sid) <= 64 else None
        return s if s is not None and server.store.session_dir(sid).is_dir() else None

    def require_session(sid: str):
        s = known_session(sid)
        if s is None:
            raise HTTPException(404, "unknown session")
        return s

    def require_room():
        """Refuse beforehand what would be written on a disk that is almost full."""
        free = free_bytes(server.store.root)
        if free is not None and free < MIN_FREE_BYTES:
            raise server.storage_refusal()

    @app.get("/health")
    def health(authorization: str | None = Header(default=None)):
        # Answers without token (the app checks that the calculator is there before pairing), but names the
        # session in progress only to a paired phone.
        a = server.active
        paired = server.store.token_ok((authorization or "").removeprefix("Bearer ").strip())
        return {"service": "dishplay-scan", "api": API_VERSION, "engine": ENGINE_VERSION, "time": time.time(),
                "active_session": a.sid if a and paired else None, "worker_alive": bool(a and a.proc.is_alive())}

    @app.post("/pair")
    async def pair(request: Request):
        body = await read_json(request)
        wait = server.pair_blocked_for()
        if wait > 0:
            seconds = math.ceil(wait)
            raise HTTPException(429, f"Trop d'essais : attendez {seconds} s avant de réessayer.", headers={"Retry-After": str(seconds)})
        if not secrets.compare_digest(str(body.get("code", "")).encode(), server.pairing_code.encode()):
            server.pair_failed()
            raise HTTPException(403, "wrong pairing code")
        server.pair_failures = 0
        token = secrets.token_urlsafe(32)
        server.store.add_token(token, str(body.get("device", ""))[:64])
        return {"token": token, "api": API_VERSION}

    @app.get("/diagnostics")
    def diagnostics(_=Depends(auth)):
        from app.diagnostics import capabilities
        return capabilities(str(server.store.root))

    @app.post("/sessions")
    async def create_session(request: Request, _=Depends(auth)):
        body = await read_json(request)
        server.validator.session(body)
        sid = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
        settings = {"use_lidar": bool(body["device"].get("lidar_enabled", False)), "texture": True}
        box = {**body["box"], "revision": 0}
        require_room()
        try:
            server.store.create_session(sid, box, body["device"], settings, body.get("reference_width_m"))
        except (OSError, sqlite3.OperationalError) as exc:
            shutil.rmtree(server.store.session_dir(sid), ignore_errors=True)
            raise server.storage_refusal(exc)
        # While another dish is being finished the scan is accepted all the same: its views are kept, and its
        # live worker starts by itself once the calculator is free ("waiting").
        how = await run_in_threadpool(server.open_session, sid, True)
        return {"session_id": sid, "events": f"/sessions/{sid}/events", "lidar_used": settings["use_lidar"], "waiting": how == "waiting"}

    @app.get("/sessions/{sid}")
    def get_session(sid: str, _=Depends(auth)):
        s = require_session(sid)
        frames = server.store.frames(sid)
        counts: dict[str, int] = {}
        for f in frames:
            counts[f[4]] = counts.get(f[4], 0) + 1
        a = server.active
        mine = a if a is not None and a.sid == sid and a.proc.is_alive() else None     # a dead process is not "active"
        final = server.store.session_dir(s["id"]) / "final"
        ready = (final / "manifest.json").exists() and (final / "model.glb").exists()   # a manifest without model is not a dish
        waiting_list = list(server.finish_queue)
        position = waiting_list.index(sid) + 1 if sid in waiting_list else None
        # `progress` and `busy_with_other` let the phone say where a calculation stands, or why it is not moving:
        # another dish is being finished (optional neural step included), or this one waits its turn.
        other = a is not None and a.sid != sid and a.finishing and a.proc.is_alive()
        failed = s["state"] == "failed"
        verdict, fallbacks = final_summary(final)
        return {**s, "frames": counts, "active": mine is not None, "last_geometry": mine.last_geometry if mine else None,
                "ready": ready, "progress": mine.last_progress if mine and mine.state == "finishing" else None,
                "busy_with_other": other or position is not None,
                "queued": position is not None, "queue_position": position, "waiting": sid in server.waiting,
                "failed": failed, "error": server.store.failure(sid) if failed else None,
                "verdict": verdict, "fallbacks": fallbacks}

    @app.post("/sessions/{sid}/resume_worker")
    def resume_worker(sid: str, _=Depends(auth)):
        require_session(sid)
        how = server.open_session(sid)
        # Always 200 for a known session. One calculation at a time: when the calculator is taken, nothing is
        # stopped, the views are accepted and kept, and this dish gets its turn ("waiting").
        return {"active": {"ok": True, "note": "already active"}, "started": {"ok": True},
                "queued": {"ok": True, "queued": True}, "waiting": {"ok": True, "waiting": True}}[how]

    @app.put("/sessions/{sid}/frames/{frame_id}")
    async def put_frame(sid: str, frame_id: int, request: Request, _=Depends(auth)):
        require_session(sid)
        body = await read_body(request, MAX_BODY, "frame too large")
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
        require_room()
        fdir = server.store.session_dir(sid) / "frames"
        base = fdir / f"{frame_id:06d}"
        meta_path = base.with_suffix(".json")
        written = []
        try:
            for suffix, blob in ((".jpg", image), (".depth", depth), (".conf", conf)):
                if blob:
                    written.append(base.with_suffix(suffix))
                    written[-1].write_bytes(blob)
            written.append(meta_path)
            meta_path.write_text(json.dumps(meta))  # written last: marks the frame complete
            server.store.add_frame(sid, frame_id, meta["epoch"], sha, bool(depth), len(body))
        except (OSError, sqlite3.OperationalError) as exc:
            # Nothing of a view that could not be stored whole is kept (the metadata goes first: without it
            # the view does not count); the phone still has it and sends it again.
            for p in reversed(written):
                try:
                    p.unlink()
                except OSError:
                    pass
            raise server.storage_refusal(exc)
        queued = await run_in_threadpool(server.frame_stored, sid, str(meta_path), time.time())
        return {"frame_id": frame_id, "duplicate": False, "status": "received", "queued": queued}

    @app.post("/sessions/{sid}/box")
    async def revise_box(sid: str, request: Request, _=Depends(auth)):
        s = require_session(sid)
        box = await read_json(request)
        server.validator.box(box)
        box["revision"] = int(s["box"].get("revision", 0)) + 1
        server.store.update_box(sid, box)
        a = server.active
        if a is not None and a.sid == sid:
            a.cmd_q.put(("box", box))
        return {"revision": box["revision"], "note": "volume rebuilt from stored frames"}

    for action in ("pause", "resume"):
        def _make(action=action):
            def handler(sid: str, _=Depends(auth)):
                require_session(sid)
                a = server.active
                if a is None or a.sid != sid:
                    raise HTTPException(409, "session not active")
                a.cmd_q.put((action,))
                return {"ok": True}
            return handler
        app.post(f"/sessions/{{sid}}/{action}")(_make())

    @app.post("/sessions/{sid}/finish")
    async def finish(sid: str, request: Request, _=Depends(auth)):
        s = require_session(sid)
        raw = await read_body(request, MAX_JSON_BODY)
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}        # a finish request needs no body
        ref = body.get("reference_width_m", s.get("reference_width_m")) if isinstance(body, dict) else s.get("reference_width_m")
        try:
            ref = float(ref) if ref else None
        except (TypeError, ValueError):
            raise HTTPException(422, "reference_width_m must be a number")
        # Works whether or not this session has a worker; while another dish is being calculated the request
        # waits its turn and starts by itself. Asking twice changes nothing.
        return await run_in_threadpool(server.request_finish, sid, ref)

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
        return {"files": files, "ready": "manifest.json" in files and "model.glb" in files}

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
        if not server.store.token_ok(token) or known_session(sid) is None:
            await ws.close(code=4401)
            return
        await ws.accept()
        a = server.active
        active = a is not None and a.sid == sid and a.proc.is_alive()
        await ws.send_text(json.dumps({"type": "hello", "session_id": sid, "server_time": time.time(), "active": active}))
        # Registered for the session, not for its process: a phone connected while its dish waits for the
        # calculator receives the events as soon as the process starts.
        listeners = server.sockets.setdefault(sid, set())
        listeners.add(ws)
        for ev in (server.last_status(sid), server.last_events.get(sid, {}).get("geometry")):
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
            listeners.discard(ws)
            if not listeners and server.sockets.get(sid) is listeners:
                del server.sockets[sid]

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
    ap.add_argument("--new-certificate", action="store_true",
                    help="make a new TLS certificate (every iPhone must then scan the pairing QR again)")
    ap.add_argument("--forget-devices", action="store_true",
                    help="forget every paired device, a lost or lent iPhone for example (every iPhone must then be paired again)")
    args = ap.parse_args(argv)
    import uvicorn
    data = Path(args.data)
    ips = lan_addresses()        # the address of the default route first: it is the one of the terminal QR
    scheme = "http" if args.insecure_http else "https"
    ssl = {}
    fp = ""
    renewed = False
    if not args.insecure_http:
        from app.tls import ensure_certificate, fingerprint
        try:
            before = fingerprint(data / "tls" / "server.crt")
        except (OSError, ValueError):
            before = None
        cert, key, fp = ensure_certificate(data / "tls", ips, new=args.new_certificate)
        renewed = before is not None and before != fp
        ssl = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
    urls = [f"{scheme}://{ip}:{args.port}" for ip in ips] or [f"{scheme}://127.0.0.1:{args.port}"]
    server = Server(data, args.code, fp, urls)
    say = server._say
    say("\n=== Calculateur DishPlay Scan ===")
    say(f"Dossier des données : {data}")
    free = free_bytes(data)
    if free is not None:
        say(f"Espace libre sur le disque des données : {human_size(free)}")
        if free < MIN_FREE_BYTES:
            say(f"ATTENTION : le disque est presque plein (moins de {human_size(MIN_FREE_BYTES)} libres). Les nouvelles vues "
                "seront refusées tant qu'il n'y a pas plus de place. Pour supprimer les anciens scans : outil tools/clean_sessions.py")
        elif free < LOW_FREE_BYTES:
            say("ATTENTION : il reste peu de place sur le disque (un scan prend 100 à 300 Mo). "
                "Pour supprimer les anciens scans : outil tools/clean_sessions.py")
    say(f"Code de jumelage : {server.pairing_code}")
    say(f"Empreinte du certificat (SHA-256) : {fp or '(aucune : HTTP sans chiffrement, pour les tests)'}")
    if args.forget_devices:
        say(f"Appareils jumelés oubliés : {server.store.forget_tokens()} appareil(s). Chaque iPhone doit être jumelé de nouveau (QR ou code).")
    if renewed:
        say("Le certificat du calculateur a été renouvelé : sur chaque iPhone déjà jumelé, rescannez le QR de jumelage.")
    for u in urls:
        say(f"Adresse : {u}\n  Lien de jumelage : {pairing_link(u, server.pairing_code, fp)}")
    try:
        import segno
        if urls and not args.insecure_http:
            segno.make(pairing_link(urls[0], server.pairing_code, fp), error="m").terminal(compact=True)
    except Exception:
        pass
    say(f"Page du QR (à ouvrir sur cet ordinateur) : {scheme}://127.0.0.1:{args.port}/")
    if server.restored:
        say(f"Reprise des calculs interrompus par l'arrêt précédent : {len(server.restored)} plat(s) ({', '.join(server.restored)}).")
    say("")
    try:
        uvicorn.run(create_app(server), host=args.host, port=args.port, log_level="info", ws_ping_interval=10,
                    timeout_graceful_shutdown=SHUTDOWN_WAIT_S, **ssl)
    finally:
        server.close()


if __name__ == "__main__":
    mp.freeze_support()
    main()
