#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir/backend"
exec "$project_dir/.venv-new-ocr/bin/python" -c 'from app.ocr.mlx_service import stop_mlx_service; print("MLX service stopped." if stop_mlx_service() else "No managed MLX service running.")'
