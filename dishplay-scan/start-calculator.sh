#!/usr/bin/env bash
# DishPlay Scan calculator — Linux / WSL2. First run installs Python deps into backend/.venv.
set -euo pipefail
cd "$(dirname "$0")/backend"
PY="${PYTHON:-python3.12}"
command -v "$PY" >/dev/null || PY=python3
if [ ! -x .venv/bin/python ]; then
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.lock
fi
.venv/bin/python ../tools/doctor.py --quick || true
exec .venv/bin/python -m app.main "$@"
