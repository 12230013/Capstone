"""Manage a loopback-only MLX-VLM sidecar without mixing backend dependencies."""
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen
from app.ocr.config import BACKEND_ROOT

_LOCK = threading.Lock()
SERVICE_DIRECTORY = BACKEND_ROOT / 'data/ocr-vl-cache'


def _health(server_url):
    try:
        with urlopen(server_url.rstrip('/') + '/health', timeout=2) as response:
            value = json.load(response)
        if value.get('status') == 'healthy' and 'loaded_model' in value:
            return value
    except (URLError, OSError, ValueError):
        pass
    return None


def ensure_mlx_service(server_url):
    """Start/reuse the local GPU service; never silently fall back to CPU."""
    parsed = urlsplit(server_url)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost'} or parsed.path not in {'', '/'}:
        raise RuntimeError('Automatic MLX startup requires a loopback HTTP service URL.')
    port = parsed.port or 80
    SERVICE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with _LOCK, (SERVICE_DIRECTORY / 'mlx-service.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        existing = _health(server_url)
        if existing is not None:
            return existing
        with socket.socket() as connection:
            if connection.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError(f'Port {port} is occupied by another service; MLX cannot start.')
        python = BACKEND_ROOT.parent / '.venv-mlx-ocr/bin/python'
        if not python.is_file():
            raise RuntimeError('Install .venv-mlx-ocr using backend/requirements-mlx-ocr.txt first.')
        command = [str(python), '-m', 'mlx_vlm.server', '--host', '127.0.0.1',
                   '--port', str(port), '--max-num-seqs', '1']
        cached = SERVICE_DIRECTORY / 'official_models/PaddleOCR-VL-1.6'
        if cached.is_dir():
            command.extend(['--model', str(cached)])
        log_path = SERVICE_DIRECTORY / 'mlx-server.log'
        environment = os.environ.copy()
        # MLX defaults to Metal on Apple Silicon. One sequence avoids excessive
        # memory usage and keeps OCR requests deterministic across table regions.
        environment['PYTHONUNBUFFERED'] = '1'
        with log_path.open('ab') as log:
            process = subprocess.Popen(command, cwd=BACKEND_ROOT, env=environment,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True)
        (SERVICE_DIRECTORY / 'mlx-server.pid').write_text(str(process.pid))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            health = _health(server_url)
            if health is not None:
                return health
            if process.poll() is not None:
                raise RuntimeError(f'MLX service exited. Check {log_path}; Metal GPU access is required.')
            time.sleep(.25)
        raise RuntimeError(f'MLX service did not become ready. Check {log_path}.')


def stop_mlx_service():
    """Stop only the sidecar recorded by this project, if it is still running."""
    import signal
    pid_file = SERVICE_DIRECTORY / 'mlx-server.pid'
    if not pid_file.exists():
        return False
    pid = int(pid_file.read_text())
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True)
    if result.returncode != 0:
        pid_file.unlink(missing_ok=True)
        return False
    if '-m mlx_vlm.server' not in result.stdout:
        raise RuntimeError('The recorded process is not the project MLX service; refusing to stop it.')
    os.kill(pid, signal.SIGTERM)
    pid_file.unlink(missing_ok=True)
    return True
