#!/usr/bin/env bash
# Start PBIX Canvas on macOS / Linux.
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -q -r backend/requirements.txt
exec .venv/bin/python run.py "$@"
