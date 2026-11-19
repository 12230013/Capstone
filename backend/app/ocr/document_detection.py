"""Classify PDFs by the amount and distribution of extractable text.

Thresholds are configurable through:
- PDF_DETECTION_MIN_PAGE_CHARS (default: 40 meaningful characters per page)
- PDF_DETECTION_MIN_DOCUMENT_CHARS (default: 100 extracted characters total)
- PDF_DETECTION_MIN_PAGE_COVERAGE (default: 0.8 of pages with usable text)

This service only extracts text with PyMuPDF. It never runs OCR.
"""

import os
import re
import unicodedata
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
    max_image_page_coverage: float = float(
        os.getenv("PDF_DETECTION_MAX_IMAGE_COVERAGE", "0.5")
    )
    min_printable_text_ratio: float = float(
        os.getenv("PDF_DETECTION_MIN_PRINTABLE_RATIO", "0.7")
    )
    min_alphanumeric_text_ratio: float = float(
        os.getenv("PDF_DETECTION_MIN_ALPHANUMERIC_RATIO", "0.45")
    )
    min_text_area_coverage: float = float(
        os.getenv("PDF_DETECTION_MIN_TEXT_AREA_COVERAGE", "0.002")
    )

    def __post_init__(self):
        if self.min_meaningful_chars_per_page < 1:
            raise ValueError("PDF_DETECTION_MIN_PAGE_CHARS must be at least 1")
        if self.min_extracted_chars_per_document < 1:
            raise ValueError("PDF_DETECTION_MIN_DOCUMENT_CHARS must be at least 1")
        if not 0 < self.min_text_page_coverage <= 1:
            raise ValueError("PDF_DETECTION_MIN_PAGE_COVERAGE must be in (0, 1]")
        if not 0 <= self.max_image_page_coverage <= 1:
            raise ValueError("PDF_DETECTION_MAX_IMAGE_COVERAGE must be in [0, 1]")
        if not 0 < self.min_printable_text_ratio <= 1:
            raise ValueError("PDF_DETECTION_MIN_PRINTABLE_RATIO must be in (0, 1]")
        if not 0 < self.min_alphanumeric_text_ratio <= 1:
            raise ValueError("PDF_DETECTION_MIN_ALPHANUMERIC_RATIO must be in (0, 1]")
        if not 0 <= self.min_text_area_coverage <= 1:
            raise ValueError("PDF_DETECTION_MIN_TEXT_AREA_COVERAGE must be in [0, 1]")


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
    image_coverages: list[float] | None = None,
    text_coverages: list[float] | None = None,
) -> dict:
    """Classify each page using text quality and raster-image coverage signals."""
    page_count = len(page_texts)
    if page_count == 0:
        raise InvalidPDFError("The PDF contains no pages")
    if image_coverages is None:
        image_coverages = [0.0] * page_count
    if len(image_coverages) != page_count:
        raise ValueError("Image coverage must be provided for every page")
    if text_coverages is None:
        text_coverages = [1.0 if text.strip() else 0.0 for text in page_texts]
    if len(text_coverages) != page_count:
        raise ValueError("Text coverage must be provided for every page")

    pages_with_text = 0
    total_text_characters = 0
    page_decisions = []
    seen_text: set[str] = set()
    for page_number, (page_text, image_coverage, text_coverage) in enumerate(
        zip(page_texts, image_coverages, text_coverages), start=1
    ):
        text = normalize_detection_text(page_text)
        meaningful_characters = sum(character.isalnum() for character in text)
        total_text_characters += len(text.replace(" ", ""))
        if meaningful_characters >= thresholds.min_meaningful_chars_per_page:
            pages_with_text += 1
        printable_ratio = (
            sum(character.isprintable() for character in text) / len(text)
            if text
            else 1.0
        )
        alphanumeric_ratio = (
            meaningful_characters / len(text)
            if text
            else 1.0
        )
        suspicious = (
            printable_ratio < thresholds.min_printable_text_ratio
            or any(unicodedata.category(character) == "Co" for character in text)
            or "\ufffd" in text
            or (
                meaningful_characters >= thresholds.min_meaningful_chars_per_page
                and alphanumeric_ratio < thresholds.min_alphanumeric_text_ratio
            )
        )
        normalized_key = text.casefold()
        duplicated = bool(text) and normalized_key in seen_text
        if text:
            seen_text.add(normalized_key)
        if suspicious or duplicated:
            decision = "manual_review_recommended"
            reason = "suspicious_or_duplicated_text"
        elif (
            meaningful_characters < thresholds.min_meaningful_chars_per_page
            or image_coverage >= thresholds.max_image_page_coverage
            or (
                meaningful_characters > 0
                and text_coverage < thresholds.min_text_area_coverage
            )
        ):
            decision = "ocr_fallback_recommended"
            if image_coverage >= thresholds.max_image_page_coverage:
                reason = "image_dominated_page"
            elif (
                meaningful_characters > 0
                and text_coverage < thresholds.min_text_area_coverage
            ):
                reason = "low_visible_text_area"
            else:
                reason = "insufficient_extractable_text"
        else:
            decision = "direct_extraction_accepted"
            reason = "text_quality_thresholds_met"
        page_decisions.append(
            {
                "page_number": page_number,
                "meaningful_characters": meaningful_characters,
                "printable_text_ratio": round(printable_ratio, 4),
                "alphanumeric_text_ratio": round(alphanumeric_ratio, 4),
                "image_coverage": round(image_coverage, 4),
                "text_area_coverage": round(text_coverage, 4),
                "decision": decision,
                "reason": reason,
            }
        )

    text_page_coverage = pages_with_text / page_count
    direct_accepted = (
        total_text_characters >= thresholds.min_extracted_chars_per_document
        and text_page_coverage >= thresholds.min_text_page_coverage
        and all(
            page["decision"] == "direct_extraction_accepted"
            for page in page_decisions
        )
    )
    if any(page["decision"] == "manual_review_recommended" for page in page_decisions):
        quality_decision = "manual_review_recommended"
    elif direct_accepted:
        quality_decision = "direct_extraction_accepted"
    else:
        quality_decision = "ocr_fallback_recommended"

    return {
        "classification": "digital_pdf" if direct_accepted else "scanned_pdf",
        "ocr_required": not direct_accepted,
        "page_count": page_count,
        "pages_with_text": pages_with_text,
        "total_text_characters": total_text_characters,
        "text_page_coverage": round(text_page_coverage, 4),
        "quality_decision": quality_decision,
        "page_decisions": page_decisions,
    }


def page_image_coverage(page: fitz.Page) -> float:
    """Estimate raster coverage from visible image rectangles on a page."""
    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return 0.0
    covered_area = 0.0
    try:
        for image in page.get_image_info(xrefs=True):
            bbox = image.get("bbox")
            if bbox is None:
                continue
            clipped = fitz.Rect(bbox) & page.rect
            if not clipped.is_empty:
                covered_area += clipped.width * clipped.height
    except (fitz.FileDataError, ValueError, RuntimeError, AttributeError) as exc:
        raise InvalidPDFError("Could not inspect PDF image coverage") from exc
    return min(covered_area / page_area, 1.0)


def page_text_area_coverage(page: fitz.Page) -> float:
    """Estimate visible text area from PyMuPDF's text-block rectangles."""
    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return 0.0
    covered_area = 0.0
    try:
        for block in page.get_text("blocks", sort=True):
            if len(block) < 7 or block[6] != 0 or not block[4].strip():
                continue
            clipped = fitz.Rect(block[:4]) & page.rect
            if not clipped.is_empty:
                covered_area += clipped.width * clipped.height
    except (fitz.FileDataError, ValueError, RuntimeError, AttributeError) as exc:
        raise InvalidPDFError("Could not inspect PDF text coverage") from exc
    return min(covered_area / page_area, 1.0)


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
        image_coverages = [page_image_coverage(page) for page in document]
        text_coverages = [page_text_area_coverage(page) for page in document]
    except (fitz.FileDataError, ValueError, RuntimeError) as exc:
        raise InvalidPDFError("The PDF could not be read") from exc

    return classify_page_texts(
        page_texts, thresholds, image_coverages, text_coverages
    )


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
