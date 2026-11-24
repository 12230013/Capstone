import importlib
import os
from pathlib import Path
import sys

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("OCR_DATA_DIR", BACKEND_ROOT / "data")).resolve()
DOCUMENTS_DIR = DATA_DIR / "documents"
OCR_RESULTS_DIR = DATA_DIR / "ocr"
TESSERACT_CMD = os.getenv("TESSERACT_CMD")
OCR_ENGINE = os.getenv("OCR_ENGINE", "paddleocr_vl").strip().lower()
if OCR_ENGINE not in {"paddleocr", "paddleocr_vl", "tesseract"}:
    raise ValueError(
        "OCR_ENGINE must be 'paddleocr', 'paddleocr_vl', or 'tesseract'"
    )
PADDLEOCR_VARIANT = os.getenv("PADDLEOCR_VARIANT", "mobile").strip().lower()
if PADDLEOCR_VARIANT != "mobile":
    raise ValueError("PADDLEOCR_VARIANT must be 'mobile'")
OCR_MODEL_ID = os.getenv(
    "OCR_MODEL_ID",
    (
        "PP-OCRv5-mobile" if OCR_ENGINE == "paddleocr" else ("PaddleOCR-VL-1.6" if OCR_ENGINE == "paddleocr_vl" else "tesseract-default")
    ),
).strip()
if not OCR_MODEL_ID:
    raise ValueError("OCR_MODEL_ID cannot be blank")
if OCR_ENGINE == "paddleocr" and OCR_MODEL_ID not in {"PP-OCRv5-mobile", "PP-OCRv5", "paddleocr-v5-mobile"}:
    raise ValueError("OCR_MODEL_ID must be a supported PP-OCRv5 identifier")
if OCR_ENGINE == "paddleocr_vl" and OCR_MODEL_ID != "PaddleOCR-VL-1.6":
    raise ValueError("The VL adapter requires OCR_MODEL_ID=PaddleOCR-VL-1.6")
PADDLEOCR_DEVICE = os.getenv("PADDLEOCR_DEVICE", "cpu").strip() or "cpu"
PADDLE_LAYOUT_MODEL_DIR = os.getenv("PADDLE_LAYOUT_MODEL_DIR", "").strip() or None
PADDLE_VL_MODEL_DIR = os.getenv("PADDLE_VL_MODEL_DIR", "").strip() or None
PADDLE_DEVICE = os.getenv("PADDLE_DEVICE", "auto").strip()
PADDLE_VL_BACKEND = os.getenv("PADDLE_VL_BACKEND", "auto").strip()
PADDLE_VL_SERVER_URL = os.getenv("PADDLE_VL_SERVER_URL", "http://127.0.0.1:8111/").strip()
PADDLE_VL_API_MODEL = os.getenv("PADDLE_VL_API_MODEL", "PaddlePaddle/PaddleOCR-VL-1.6").strip()
OCR_CPU_THREADS = int(os.getenv("OCR_CPU_THREADS", str(os.cpu_count() or 1)))
if OCR_CPU_THREADS < 1: raise ValueError("OCR_CPU_THREADS must be positive")
PADDLEOCR_MOBILE_DET_MODEL_DIR = (
    os.getenv("PADDLEOCR_MOBILE_DET_MODEL_DIR", "").strip() or None
)
PADDLEOCR_MOBILE_REC_MODEL_DIR = (
    os.getenv("PADDLEOCR_MOBILE_REC_MODEL_DIR", "").strip() or None
)
OCR_RENDER_DPI = int(os.getenv("OCR_RENDER_DPI", "250"))
OCR_MAX_UPLOAD_BYTES = int(os.getenv("OCR_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
if OCR_MAX_UPLOAD_BYTES < 1:
    raise ValueError("OCR_MAX_UPLOAD_BYTES must be positive")

APP_ENV = os.getenv("APP_ENV", "unset").strip().lower()
_CONFIG_INITIALIZED = False


def _environment_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


OCR_DEPLOYMENT_ENABLED = _environment_bool("OCR_DEPLOYMENT_ENABLED", False)
OCR_DEV_REVIEW_ENABLED = _environment_bool("OCR_DEV_REVIEW_ENABLED", False)
if OCR_DEV_REVIEW_ENABLED and APP_ENV not in {"development", "dev", "local"}:
    raise ValueError(
        "OCR_DEV_REVIEW_ENABLED can only be enabled in a development environment"
    )

OCR_PREPROCESSING_ENABLED = _environment_bool("OCR_PREPROCESSING_ENABLED", True)
PADDLEOCR_PREPROCESSING_ENABLED = _environment_bool(
    "PADDLEOCR_PREPROCESSING_ENABLED", True
)
OCR_DENOISE_ENABLED = _environment_bool("OCR_DENOISE_ENABLED", True)
OCR_CONTRAST_ENABLED = _environment_bool("OCR_CONTRAST_ENABLED", True)
OCR_THRESHOLD_ENABLED = _environment_bool("OCR_THRESHOLD_ENABLED", True)
OCR_DESKEW_ENABLED = _environment_bool("OCR_DESKEW_ENABLED", True)
OCR_THRESHOLD_METHOD = os.getenv("OCR_THRESHOLD_METHOD", "adaptive").strip().lower()


def initialize_config() -> None:
    """Load backend .env values before importing OCR modules that bind settings."""
    global _CONFIG_INITIALIZED
    if _CONFIG_INITIALIZED:
        return
    load_dotenv(BACKEND_ROOT / ".env")
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(BACKEND_ROOT / "data/ocr-vl-cache"))
    importlib.reload(sys.modules[__name__])
    _CONFIG_INITIALIZED = True


def validate_runtime():
    if OCR_ENGINE != 'paddleocr_vl': return
    from importlib.metadata import PackageNotFoundError, version
    from packaging.version import Version
    try: installed = version('paddleocr')
    except PackageNotFoundError: installed = '0'
    if Version(installed) < Version('3.6.0'):
        raise RuntimeError(f'PaddleOCR-VL 1.6 requires PaddleOCR >=3.6.0; {sys.prefix} has {installed}. Install backend/requirements.txt in the active environment.')
    from app.ocr.hardware import select_hardware
    selected = select_hardware(PADDLE_VL_BACKEND, PADDLE_DEVICE, cpu_threads=OCR_CPU_THREADS)
    if selected.backend == 'mlx-vlm-server' and not (BACKEND_ROOT.parent / '.venv-mlx-ocr/bin/python').is_file():
        raise RuntimeError('Apple GPU OCR requires .venv-mlx-ocr. See backend/OCR_RUNTIME.md to install the Metal service environment.')
    print(f'OCR: PaddleOCR-VL 1.6; recognition={selected.recognition_device}; layout={selected.device}; backend={selected.backend}', flush=True)
