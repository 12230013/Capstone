"""Select supported OCR acceleration from the actual platform and runtime."""
from dataclasses import asdict, dataclass
import importlib
import os
import platform
import subprocess


@dataclass(frozen=True)
class OCRHardware:
    backend: str
    device: str
    recognition_device: str
    cpu_threads: int

    def as_dict(self):
        return asdict(self)


def _nvidia_present():
    try:
        result = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'],
            capture_output=True, text=True, timeout=5)
        return result.returncode == 0 and bool(result.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


def select_hardware(backend='auto', device='auto', *, system=None, machine=None,
                    paddle_module=None, nvidia_probe=None, cpu_threads=None):
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    threads = cpu_threads if cpu_threads is not None else (os.cpu_count() or 1)
    if threads < 1: raise ValueError('OCR_CPU_THREADS must be positive.')
    if backend not in {'auto','native','mlx-vlm-server'}:
        raise ValueError('Unsupported OCR inference backend.')
    apple = system == 'Darwin' and machine in {'arm64','aarch64'}
    if backend == 'auto': backend = 'mlx-vlm-server' if apple else 'native'
    if backend == 'mlx-vlm-server':
        # The CPU runs layout detection; MLX uses Metal for recognition.
        return OCRHardware(backend, 'cpu', 'metal', threads)
    if device != 'auto':
        return OCRHardware(backend, device, device, threads)
    try:
        paddle = paddle_module or importlib.import_module('paddle')
    except ImportError as exc:
        raise RuntimeError('Install the Paddle runtime described in backend/OCR_RUNTIME.md before running OCR.') from exc
    try:
        cuda_build = paddle.is_compiled_with_cuda()
        gpu_count = paddle.device.cuda.device_count() if cuda_build else 0
    except Exception as exc:
        raise RuntimeError('The Paddle CUDA runtime could not initialize. Check the NVIDIA driver and CUDA wheel version.') from exc
    if gpu_count > 0:
        return OCRHardware(backend, 'gpu:0', 'gpu:0', threads)
    if (nvidia_probe or _nvidia_present)():
        raise RuntimeError('An NVIDIA GPU was detected but Paddle cannot use it. Install paddlepaddle-gpu with the matching CUDA wheel; see backend/OCR_RUNTIME.md. CPU and GPU Paddle packages must not be installed together.')
    return OCRHardware(backend, 'cpu', 'cpu', threads)
