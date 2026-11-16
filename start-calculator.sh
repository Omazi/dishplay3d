#!/usr/bin/env bash
# DishPlay Scan calculator — Linux / WSL2. First run installs Python deps into backend/.venv.
set -euo pipefail
cd "$(dirname "$0")/backend"
PY="${PYTHON:-python3.12}"
command -v "$PY" >/dev/null || PY=python3
if [ ! -x .venv/bin/python ]; then
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
fi
# Install the libraries again whenever the list changed (after an update of the project).
lock="$(sha256sum requirements.lock | cut -d' ' -f1)"
if [ "$(cat .venv/requirements.sha256 2>/dev/null || true)" != "$lock" ]; then
  echo "Installing the calculator's libraries..."
  if .venv/bin/python -m pip install -r requirements.lock; then
    printf '%s' "$lock" > .venv/requirements.sha256
  else
    echo "Some libraries could not be installed (no internet?). Starting with what is there; it will be tried again next time."
  fi
fi
# Optional depth model for uniform or shiny dishes (about 99 MB, once). DISHPLAY_MONO=0 skips it.
if [ "${DISHPLAY_MONO:-1}" != "0" ]; then
  .venv/bin/python ../tools/get_models.py || true
fi
.venv/bin/python ../tools/doctor.py --quick || true
exec .venv/bin/python -m app.main "$@"
