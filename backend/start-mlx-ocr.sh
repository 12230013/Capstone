#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec "$project_dir/.venv-mlx-ocr/bin/python" -m mlx_vlm.server --host 127.0.0.1 --port 8111 --max-num-seqs 1 "$@"
