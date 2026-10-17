#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -x ".venv/bin/python" ]]; then
  echo "[Movie Modify] Creating a Linux Python environment..."
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python -m movie_modify "$@"
