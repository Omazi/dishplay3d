#!/usr/bin/env python3
"""Make room on the calculator's disk by removing old scans. Nothing is removed unless --apply is given.

  python tools/clean_sessions.py                        list what would be removed (untouched for 30 days)
  python tools/clean_sessions.py --days 60              same, untouched for 60 days
  python tools/clean_sessions.py --apply                really remove
  python tools/clean_sessions.py --apply --with-final   also remove old finished dishes, final model included

On Windows, from the project folder:  backend\\.venv\\Scripts\\python.exe tools\\clean_sessions.py

What is removed, among the scans nothing has touched for more than N days:
  - a finished dish (final/model.glb exists): its raw views (frames/) and intermediate previews (preview/).
    Its final model (final/) is kept, unless --with-final is given: then the whole folder goes.
  - a scan that never produced a model: its whole folder. The calculator then answers "unknown session",
    and the iPhone says that the PC no longer knows this scan.
Never touched: a scan used during the last hour, a dish whose final calculation is running or waiting its
turn, and anything that is not a session folder of the calculator. The tool only reads the database.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.diagnostics import free_bytes, human_size  # noqa: E402  (standard library only)

SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{6,64}$")   # as in backend/app/store.py
DAY = 86400.0
MIN_IDLE_S = 3600.0     # whatever --days says, a scan touched more recently than this is in use


def say(text: str = ""):
    """One line on the console (a console that cannot show accents must not stop the tool)."""
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode(), flush=True)


def measure(path: Path) -> tuple[int, float]:
    """Size in bytes of the files under `path`, and when the newest of them was written. Only files count for
    the date: removing the views of a dish must not make it look recently used. Links are not followed."""
    total, newest = 0, 0.0
    stack = [path]
    while stack:
        p = stack.pop()
        try:
            st = os.lstat(p)
        except OSError:
            continue
        if os.path.isdir(p) and not os.path.islink(p):
            try:
                stack.extend(Path(e.path) for e in os.scandir(p))
            except OSError:
                pass
        else:
            total += st.st_size
            newest = max(newest, st.st_mtime)
    return total, newest


def protected_sessions(data: Path) -> set[str] | None:
    """Sessions whose final calculation is running or waiting its turn, read from the calculator's database
    without writing to it. An empty set when there is no database; None when it cannot be read."""
    db = data / "dishplay-scan.sqlite3"
    if not db.exists():
        return set()
    try:
        con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            ids = {r[0] for r in con.execute("SELECT id FROM sessions WHERE state IN ('finishing', 'queued')")}
            try:
                ids |= {r[0] for r in con.execute("SELECT session_id FROM finish_requests")}
            except sqlite3.OperationalError:
                pass    # database of a calculator from before the queue: no such table
            return ids
        finally:
            con.close()
    except sqlite3.Error:
        return None


def plan(data: Path, days: float = 30, with_final: bool = False, now: float | None = None, protected=()) -> list[dict]:
    """What would be removed, oldest session first: {"session", "what": "views" | "session", "finished",
    "age_days", "bytes", "paths"}. Nothing is touched here."""
    now = time.time() if now is None else now
    root = Path(data) / "sessions"
    actions = []
    for d in sorted(root.iterdir()) if root.is_dir() else []:
        if not SESSION_ID.match(d.name) or d.is_symlink() or not d.is_dir() or not (d / "session.json").is_file():
            continue    # not a session folder of the calculator
        if d.name in protected:
            continue
        size, newest = measure(d)
        idle = now - newest
        if idle < max(days * DAY, MIN_IDLE_S):
            continue
        finished = (d / "final" / "model.glb").is_file()
        if finished and not with_final:
            paths = [Path(e.path) for sub in ("frames", "preview") if (d / sub).is_dir() for e in os.scandir(d / sub)]
            size = sum(measure(p)[0] for p in paths)
            what = "views"
        else:
            paths, what = [d], "session"
        if paths:
            actions.append({"session": d.name, "what": what, "finished": finished, "age_days": idle / DAY, "bytes": size, "paths": paths})
    return actions


def remove(action: dict) -> list[str]:
    """Carry out one action of plan(). Returns what could not be removed (a file in use, for example)."""
    failed = []
    for p in action["paths"]:
        try:
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p)
            else:
                p.unlink()
        except OSError as exc:
            failed.append(f"{p} ({exc.strerror or exc})")
    return failed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Supprime les anciens scans du calculateur DishPlay Scan (essai seulement, sauf avec --apply).")
    ap.add_argument("--data", default=os.environ.get("DISHPLAY_DATA", str(Path.home() / "dishplay-scan-data")),
                    help="dossier des données du calculateur")
    ap.add_argument("--days", type=float, default=30, help="ne toucher que les scans inutilisés depuis plus de N jours (30 par défaut)")
    ap.add_argument("--apply", action="store_true", help="supprimer vraiment (sans cette option, rien n'est supprimé)")
    ap.add_argument("--with-final", action="store_true",
                    help="supprimer aussi le modèle final des anciens plats terminés (leur dossier entier)")
    a = ap.parse_args(argv)
    data = Path(a.data)
    if a.days < 0:
        say("--days doit être positif.")
        return 2
    say(f"Nettoyage des scans du calculateur. Dossier des données : {data}")
    protected = protected_sessions(data)
    if protected is None:
        say("La base du calculateur est illisible pour le moment : impossible de savoir quels plats attendent leur calcul.")
        if a.apply:
            say("Rien n'a été supprimé. Réessayez plus tard, ou fermez d'abord le calculateur.")
            return 2
        protected = set()
    actions = plan(data, a.days, a.with_final, protected=protected)
    if not actions:
        say(f"Aucun scan à supprimer (rien d'inutilisé depuis plus de {a.days:g} jours).")
        return 0
    kept = "le modèle final est supprimé aussi" if a.with_final else "le modèle final est gardé"
    say(f"Scans inutilisés depuis plus de {a.days:g} jours :")
    failures = []
    for act in actions:
        if act["what"] == "views":
            detail = f"plat terminé : vues et aperçus intermédiaires ({kept})"
        elif act["finished"]:
            detail = f"plat terminé : dossier entier ({kept})"
        else:
            detail = "scan sans modèle : dossier entier"
        say(f"  {act['session']}  {act['age_days']:.0f} j  {human_size(act['bytes']):>9}  {detail}")
        if a.apply:
            failures += remove(act)
    total = human_size(sum(act["bytes"] for act in actions))
    plural = "s" if len(actions) > 1 else ""
    if not a.apply:
        say(f"Total : {len(actions)} scan{plural}, {total} à libérer.")
        say("ESSAI SEULEMENT : rien n'a été supprimé. Pour supprimer vraiment, relancez la même commande avec --apply")
        return 0
    for f in failures:
        say(f"  Non supprimé : {f}")
    say(f"Total : {len(actions)} scan{plural} nettoyé{plural}, environ {total} libérés.")
    free = free_bytes(data)
    if free is not None:
        say(f"Espace libre sur le disque des données : {human_size(free)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
