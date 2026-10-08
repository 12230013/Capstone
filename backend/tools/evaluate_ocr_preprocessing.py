"""Compare baseline and preprocessed Tesseract OCR on synthetic documents.

Run from the backend root with:
    python tools/evaluate_ocr_preprocessing.py
"""

import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from PIL import Image
from pytesseract.pytesseract import TesseractError, TesseractNotFoundError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.ocr.config import TESSERACT_CMD
from app.ocr.document_preprocessing import preprocess_image

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD or "tesseract"


@dataclass
class SyntheticSample:
    name: str
    expected_text: str
    pages: list[np.ndarray]


def character_error_rate(expected: str, actual: str) -> float:
    """Return character edit distance divided by the ground-truth length."""
    expected = expected.strip()
    actual = actual.strip()
    if not expected:
        return 0.0 if not actual else 1.0

    previous = list(range(len(actual) + 1))
    for row, expected_character in enumerate(expected, start=1):
        current = [row]
        for column, actual_character in enumerate(actual, start=1):
            current.append(
                min(
                    current[column - 1] + 1,
                    previous[column] + 1,
                    previous[column - 1]
                    + (expected_character != actual_character),
                )
            )
        previous = current
    return previous[-1] / len(expected)


def _render_text(text: str, foreground: int = 0, background: int = 255) -> np.ndarray:
    image = np.full((260, 1200, 3), background, dtype=np.uint8)
    cv2.putText(
        image,
        text,
        (35, 145),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.25,
        (foreground, foreground, foreground),
        3,
        cv2.LINE_AA,
    )
    return image


def make_synthetic_samples() -> list[SyntheticSample]:
    """Generate clean, skewed, low-contrast, noisy, and multi-page samples."""
    ground_truth = "ACC CASE 2026 PAYMENT RECORD 12345"
    clean = _render_text(ground_truth)

    height, width = clean.shape[:2]
    rotation = cv2.getRotationMatrix2D((width / 2, height / 2), 4.0, 1.0)
    rotated = cv2.warpAffine(
        clean,
        rotation,
        (width, height),
        borderValue=(255, 255, 255),
    )

    low_contrast = _render_text(ground_truth, foreground=145, background=220)
    rng = np.random.default_rng(2026)
    noise = rng.normal(0, 18, clean.shape).astype(np.int16)
    noisy = np.clip(clean.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    second_page_text = "WITNESS PAYMENT DATE 14 MARCH 2026"
    return [
        SyntheticSample("clean-printed", ground_truth, [clean]),
        SyntheticSample("slightly-rotated", ground_truth, [rotated]),
        SyntheticSample("low-contrast", ground_truth, [low_contrast]),
        SyntheticSample("noisy-scan", ground_truth, [noisy]),
        SyntheticSample(
            "multi-page",
            f"{ground_truth} {second_page_text}",
            [clean, _render_text(second_page_text)],
        ),
    ]


def _recognize(image: Image.Image) -> str:
    return pytesseract.image_to_string(image, config="--psm 6").strip()


def evaluate() -> int:
    try:
        pytesseract.get_tesseract_version()
    except (TesseractNotFoundError, FileNotFoundError, TesseractError):
        print(
            "Evaluation requires the native Tesseract executable. "
            "Install it separately or configure TESSERACT_CMD; no OCR "
            "measurements were made."
        )
        return 2

    print("| Document | Baseline CER | Preprocessed CER | Difference |")
    print("|---|---:|---:|---:|")
    for sample in make_synthetic_samples():
        baseline_pages = []
        processed_pages = []
        for page in sample.pages:
            original_image = Image.fromarray(page, mode="RGB")
            processed_image, _ = preprocess_image(original_image)
            try:
                baseline_pages.append(_recognize(original_image))
                processed_pages.append(_recognize(processed_image))
            finally:
                if processed_image is not original_image:
                    processed_image.close()
                original_image.close()

        baseline = character_error_rate(
            sample.expected_text,
            " ".join(baseline_pages),
        )
        preprocessed = character_error_rate(
            sample.expected_text,
            " ".join(processed_pages),
        )
        print(
            f"| {sample.name} | {baseline:.3f} | {preprocessed:.3f} "
            f"| {preprocessed - baseline:+.3f} |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(evaluate())
