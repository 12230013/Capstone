#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ ! -x "$project_dir/.venv-new-ocr/bin/python" ]; then
  echo 'Create .venv-new-ocr and install backend/requirements-new-ocr.txt first.' >&2
  exit 1
fi
cd "$project_dir/backend"
exec "$project_dir/.venv-new-ocr/bin/python" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001 "$@"
