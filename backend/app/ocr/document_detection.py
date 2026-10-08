"""Classify PDFs by the amount and distribution of extractable text.

Thresholds are configurable through:
- PDF_DETECTION_MIN_PAGE_CHARS (default: 40 meaningful characters per page)
- PDF_DETECTION_MIN_DOCUMENT_CHARS (default: 100 extracted characters total)
- PDF_DETECTION_MIN_PAGE_COVERAGE (default: 0.8 of pages with usable text)

This service only extracts text with PyMuPDF. It never runs OCR.
"""

import os
import re
from dataclasses import dataclass

import fitz


class InvalidPDFError(ValueError):
    """Raised when a file cannot be opened or read as a PDF."""


@dataclass(frozen=True)
class DetectionThresholds:
    min_meaningful_chars_per_page: int = int(
        os.getenv("PDF_DETECTION_MIN_PAGE_CHARS", "40")
    )
    min_extracted_chars_per_document: int = int(
        os.getenv("PDF_DETECTION_MIN_DOCUMENT_CHARS", "100")
    )
    min_text_page_coverage: float = float(
        os.getenv("PDF_DETECTION_MIN_PAGE_COVERAGE", "0.8")
    )

    def __post_init__(self):
        if self.min_meaningful_chars_per_page < 1:
            raise ValueError("PDF_DETECTION_MIN_PAGE_CHARS must be at least 1")
        if self.min_extracted_chars_per_document < 1:
            raise ValueError("PDF_DETECTION_MIN_DOCUMENT_CHARS must be at least 1")
        if not 0 < self.min_text_page_coverage <= 1:
            raise ValueError("PDF_DETECTION_MIN_PAGE_COVERAGE must be in (0, 1]")


def open_pdf_document(pdf_path: str) -> fitz.Document:
    """Open a PDF, converting PyMuPDF open errors to the shared domain error."""
    try:
        return fitz.open(pdf_path)
    except (fitz.FileDataError, ValueError, RuntimeError) as exc:
        raise InvalidPDFError("The uploaded file is not a readable PDF") from exc


def normalize_detection_text(text: str) -> str:
    """Collapse whitespace for stable meaningful-text measurement."""
    return " ".join(text.split())


def classify_page_texts(
    page_texts: list[str],
    thresholds: DetectionThresholds = DetectionThresholds(),
) -> dict:
    """Classify extracted page text using the configured Step 2.1 thresholds."""
    page_count = len(page_texts)
    if page_count == 0:
        raise InvalidPDFError("The PDF contains no pages")

    pages_with_text = 0
    total_text_characters = 0
    for page_text in page_texts:
        text = normalize_detection_text(page_text)
        meaningful_characters = sum(character.isalnum() for character in text)
        total_text_characters += len(text.replace(" ", ""))
        if meaningful_characters >= thresholds.min_meaningful_chars_per_page:
            pages_with_text += 1

    text_page_coverage = pages_with_text / page_count
    is_digital = (
        total_text_characters >= thresholds.min_extracted_chars_per_document
        and text_page_coverage >= thresholds.min_text_page_coverage
    )

    return {
        "classification": "digital_pdf" if is_digital else "scanned_pdf",
        "ocr_required": not is_digital,
        "page_count": page_count,
        "pages_with_text": pages_with_text,
        "total_text_characters": total_text_characters,
        "text_page_coverage": round(text_page_coverage, 4),
    }


def detect_pdf_document(
    document,
    thresholds: DetectionThresholds = DetectionThresholds(),
) -> dict:
    """Classify an already-open PyMuPDF document."""
    try:
        page_texts = [
            page.get_text("text", sort=True)
            for page in document
        ]
    except (fitz.FileDataError, ValueError, RuntimeError) as exc:
        raise InvalidPDFError("The PDF could not be read") from exc

    return classify_page_texts(page_texts, thresholds)


def detect_pdf_text(
    pdf_path: str,
    thresholds: DetectionThresholds = DetectionThresholds(),
) -> dict:
    """Open a PDF and return text-extraction statistics and OCR requirement."""
    document = open_pdf_document(pdf_path)
    try:
        return detect_pdf_document(document, thresholds)
    finally:
        document.close()


def normalize_extracted_page_text(text: str) -> str:
    """Normalize spacing while retaining page line breaks and paragraph gaps."""
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.split("\n")]
    normalized = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", normalized).strip()
