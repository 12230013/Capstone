#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir/backend"
exec "$project_dir/.venv/bin/python" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001 "$@"
