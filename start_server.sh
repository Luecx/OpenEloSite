#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_ACTIVATE="$ROOT_DIR/.venv/bin/activate"
SERVER_DIR="$ROOT_DIR/server"

if [[ ! -f "$VENV_ACTIVATE" ]]; then
  echo "Missing virtual environment activation script: $VENV_ACTIVATE" >&2
  exit 1
fi

if [[ ! -d "$SERVER_DIR" ]]; then
  echo "Missing server directory: $SERVER_DIR" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$VENV_ACTIVATE"

cd "$SERVER_DIR"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 "$@"
