import os
from pathlib import Path

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_ROOT / ".env")
DATA_DIR = Path(os.getenv("OCR_DATA_DIR", BACKEND_ROOT / "data")).resolve()
DOCUMENTS_DIR = DATA_DIR / "documents"
OCR_RESULTS_DIR = DATA_DIR / "ocr"
TESSERACT_CMD = os.getenv("TESSERACT_CMD")
OCR_RENDER_DPI = int(os.getenv("OCR_RENDER_DPI", "250"))


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


OCR_PREPROCESSING_ENABLED = _environment_bool("OCR_PREPROCESSING_ENABLED", True)
OCR_DENOISE_ENABLED = _environment_bool("OCR_DENOISE_ENABLED", True)
OCR_CONTRAST_ENABLED = _environment_bool("OCR_CONTRAST_ENABLED", True)
OCR_THRESHOLD_ENABLED = _environment_bool("OCR_THRESHOLD_ENABLED", True)
OCR_DESKEW_ENABLED = _environment_bool("OCR_DESKEW_ENABLED", True)
OCR_THRESHOLD_METHOD = os.getenv("OCR_THRESHOLD_METHOD", "adaptive").strip().lower()
