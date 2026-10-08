"""Tesseract OCR for scanned PDFs and supported image documents."""

import os
import statistics
import tempfile
import json
from datetime import datetime, timezone
from typing import Any

import fitz
import pytesseract
from PIL import Image, ImageOps, UnidentifiedImageError
from pytesseract import Output
from pytesseract.pytesseract import TesseractError, TesseractNotFoundError

from app.ocr.config import OCR_RENDER_DPI, OCR_RESULTS_DIR, TESSERACT_CMD
from app.ocr.document_detection import (
    InvalidPDFError,
    classify_page_texts,
    open_pdf_document,
)
from app.ocr.document_preprocessing import (
    ImagePreprocessingError,
    preprocess_image,
    preprocessing_settings,
)

SUPPORTED_IMAGE_TYPES = {
    "image/png",
    "image/jpeg",
}
MAX_RENDER_DPI = 600


class TesseractUnavailableError(RuntimeError):
    """Raised when the Tesseract application cannot be found or started."""


class InvalidOCRDocumentError(ValueError):
    """Raised for unreadable PDFs or invalid image documents."""


class OCRProcessingError(RuntimeError):
    """Raised when Tesseract fails while processing a readable image."""


def _configured_dpi() -> int:
    if not 72 <= OCR_RENDER_DPI <= MAX_RENDER_DPI:
        raise OCRProcessingError(
            f"OCR_RENDER_DPI must be between 72 and {MAX_RENDER_DPI}"
        )
    return OCR_RENDER_DPI


def _ensure_tesseract_available() -> None:
    if TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    try:
        pytesseract.get_tesseract_version()
    except (TesseractNotFoundError, FileNotFoundError) as exc:
        raise TesseractUnavailableError(
            "Tesseract is not installed or could not be found. Install the "
            "Tesseract executable and set TESSERACT_CMD if it is not on PATH."
        ) from exc
    except TesseractError as exc:
        raise TesseractUnavailableError(
            "Tesseract is installed but could not be started."
        ) from exc


def _confidence_values(data: dict[str, Any]) -> list[float]:
    confidences = []
    for value in data.get("conf", []):
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            continue
        if confidence >= 0:
            confidences.append(confidence)
    return confidences


def _ocr_page(image: Image.Image) -> tuple[str, float | None, list[float]]:
    try:
        text = pytesseract.image_to_string(image)
        data = pytesseract.image_to_data(image, output_type=Output.DICT)
    except (TesseractNotFoundError, FileNotFoundError) as exc:
        raise TesseractUnavailableError(
            "Tesseract is not installed or could not be found. Install the "
            "Tesseract executable and set TESSERACT_CMD if it is not on PATH."
        ) from exc
    except TesseractError as exc:
        raise OCRProcessingError("Tesseract failed to process the document.") from exc
    except Exception as exc:
        raise OCRProcessingError("Tesseract failed to process the document.") from exc

    confidence_values = _confidence_values(data)
    confidence = (
        round(statistics.mean(confidence_values), 1)
        if confidence_values
        else None
    )
    return text.strip(), confidence, confidence_values


def _render_pdf_page(page: fitz.Page, dpi: int) -> Image.Image:
    scale = dpi / 72
    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(scale, scale),
        colorspace=fitz.csRGB,
        alpha=False,
    )
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def _preprocess_and_ocr_page(
    image: Image.Image,
) -> tuple[str, float | None, list[float], dict[str, Any]]:
    try:
        ocr_image, preprocessing = preprocess_image(image)
    except ImagePreprocessingError as exc:
        raise OCRProcessingError(
            "Image preprocessing failed. Check the preprocessing settings and input."
        ) from exc

    try:
        text, confidence, confidence_values = _ocr_page(ocr_image)
        return text, confidence, confidence_values, preprocessing
    finally:
        if ocr_image is not image:
            ocr_image.close()


def _base_result(
    document_id: str,
    filename: str,
    file_type: str,
    document_classification: str,
    page_count: int,
    dpi: int | None,
) -> dict:
    return {
        "document_id": document_id,
        "filename": filename,
        "document_type": "pdf" if file_type == "application/pdf" else "image",
        "document_classification": document_classification,
        "ocr_engine": "tesseract",
        "ocr_required": True,
        "ocr_status": "failed",
        "page_count": page_count,
        "pages": [],
        "average_confidence": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "processing_metadata": {
            "render_dpi": dpi,
            "preprocessing": preprocessing_settings(),
            "confidence_calculation": (
                "Arithmetic mean of non-negative Tesseract word confidences; "
                "null when Tesseract provides none."
            ),
        },
    }


def failed_ocr_result(
    document_id: str,
    filename: str,
    file_type: str,
    error_message: str,
    document_classification: str = "unknown",
    page_count: int = 0,
    dpi: int | None = None,
) -> dict:
    if file_type in SUPPORTED_IMAGE_TYPES:
        document_classification = "image"
        page_count = 1
    result = _base_result(
        document_id,
        filename,
        file_type,
        document_classification,
        page_count,
        dpi,
    )
    result["error_message"] = error_message
    return result


def save_ocr_result(result: dict) -> str:
    """Atomically persist OCR output as data/ocr/{document_id}.json."""
    os.makedirs(OCR_RESULTS_DIR, exist_ok=True)
    result_path = os.path.join(OCR_RESULTS_DIR, f"{result['document_id']}.json")
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{result['document_id']}-",
            suffix=".tmp",
            dir=OCR_RESULTS_DIR,
            delete=False,
        ) as temporary_file:
            temporary_path = temporary_file.name
            json.dump(result, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, result_path)
        return result_path
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.remove(temporary_path)


def run_document_ocr(
    file_path: str,
    document_id: str,
    filename: str,
    file_type: str,
) -> dict:
    """OCR an image or scanned PDF, refusing digital PDFs."""
    if file_type not in {"application/pdf", *SUPPORTED_IMAGE_TYPES}:
        raise InvalidOCRDocumentError("OCR supports PDF, PNG, JPG, and JPEG files only.")

    dpi = None
    document = None
    if file_type == "application/pdf":
        try:
            document = open_pdf_document(file_path)
            page_texts = [
                page.get_text("text", sort=True)
                for page in document
            ]
            detection = classify_page_texts(page_texts)
        except InvalidPDFError as exc:
            if document is not None:
                document.close()
            raise InvalidOCRDocumentError(
                "The PDF is invalid or could not be read."
            ) from exc
        except (fitz.FileDataError, ValueError, RuntimeError) as exc:
            if document is not None:
                document.close()
            raise InvalidOCRDocumentError(
                "The PDF is invalid or could not be read."
            ) from exc

        if detection["classification"] == "digital_pdf":
            document.close()
            return {
                "document_id": document_id,
                "document_type": "pdf",
                "document_classification": "digital_pdf",
                "ocr_required": False,
                "ocr_status": "not_required",
                "extraction_method": "direct",
                "message": (
                    "This PDF contains selectable text. Use "
                    f"POST /documents/{document_id}/extract instead."
                ),
            }
        document_classification = "scanned_pdf"
        page_count = detection["page_count"]
        dpi = _configured_dpi()
    else:
        document_classification = "image"
        page_count = 1

    result = _base_result(
        document_id,
        filename,
        file_type,
        document_classification,
        page_count,
        dpi,
    )
    try:
        image = None
        if file_type in SUPPORTED_IMAGE_TYPES:
            try:
                with Image.open(file_path) as source:
                    image = ImageOps.exif_transpose(source).convert("RGB")
            except (UnidentifiedImageError, OSError, ValueError) as exc:
                raise InvalidOCRDocumentError(
                    "The uploaded image is invalid or could not be read."
                ) from exc

        _ensure_tesseract_available()
        confidence_values = []

        if file_type == "application/pdf":
            for page_number, page in enumerate(document, start=1):
                image = _render_pdf_page(page, dpi)
                try:
                    (
                        text,
                        page_confidence,
                        page_confidence_values,
                        page_preprocessing,
                    ) = _preprocess_and_ocr_page(image)
                finally:
                    image.close()
                confidence_values.extend(page_confidence_values)
                result["pages"].append(
                    {
                        "page_number": page_number,
                        "text": text,
                        "confidence": page_confidence,
                        "preprocessing": page_preprocessing,
                    }
                )
        else:
            (
                text,
                page_confidence,
                page_confidence_values,
                page_preprocessing,
            ) = _preprocess_and_ocr_page(image)
            confidence_values.extend(page_confidence_values)
            result["pages"].append(
                {
                    "page_number": 1,
                    "text": text,
                    "confidence": page_confidence,
                    "preprocessing": page_preprocessing,
                }
            )

        if not any(page["text"] for page in result["pages"]):
            result["error_message"] = (
                "Tesseract completed but did not recognize any text."
            )
            return result

        result["ocr_status"] = "completed"
        result["average_confidence"] = (
            round(statistics.mean(confidence_values), 1)
            if confidence_values
            else None
        )
        return result
    except (TesseractUnavailableError, InvalidOCRDocumentError, OCRProcessingError):
        raise
    except (fitz.FileDataError, ValueError, RuntimeError) as exc:
        raise InvalidOCRDocumentError(
            "The document could not be rendered or read."
        ) from exc
    finally:
        if image is not None:
            image.close()
        if document is not None:
            document.close()
