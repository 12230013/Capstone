
"""PaddleOCR-VL 1.6 for scanned PDFs and supported image documents."""

import json
import os
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import fitz
from PIL import Image, ImageOps, UnidentifiedImageError

from app.ocr.config import OCR_RENDER_DPI, OCR_RESULTS_DIR
from app.ocr.document_detection import (
    InvalidPDFError,
    classify_page_texts,
    open_pdf_document,
)


SUPPORTED_IMAGE_TYPES = {
    "image/png",
    "image/jpeg",
}

MAX_RENDER_DPI = 600
OCR_ENGINE_NAME = "paddleocr-vl-1.6"

# Load the large model only once per Python process.
_PADDLEOCR_PIPELINE = None


class PaddleOCRUnavailableError(RuntimeError):
    """Raised when PaddleOCR-VL cannot be loaded."""


class InvalidOCRDocumentError(ValueError):
    """Raised for unreadable PDFs or invalid image documents."""


class OCRProcessingError(RuntimeError):
    """Raised when PaddleOCR-VL fails to process a readable document."""


def _configured_dpi() -> int:
    """Validate the resolution used to render scanned PDF pages."""
    if not 72 <= OCR_RENDER_DPI <= MAX_RENDER_DPI:
        raise OCRProcessingError(
            f"OCR_RENDER_DPI must be between 72 and {MAX_RENDER_DPI}."
        )
    return OCR_RENDER_DPI


def _get_paddleocr_pipeline():
    """Initialize PaddleOCR-VL 1.6 once and reuse it."""
    global _PADDLEOCR_PIPELINE

    if _PADDLEOCR_PIPELINE is not None:
        return _PADDLEOCR_PIPELINE

    try:
        from paddleocr import PaddleOCRVL

        _PADDLEOCR_PIPELINE = PaddleOCRVL(
            pipeline_version="v1.6",
            device="cpu",
            use_doc_orientation_classify=True,
            use_doc_unwarping=True,
            use_layout_detection=True,
            use_chart_recognition=True,
            use_seal_recognition=True,
            format_block_content=True,
        )

    except Exception as exc:
        raise PaddleOCRUnavailableError(
            "PaddleOCR-VL 1.6 could not be initialized. "
            "Check the PaddleOCR installation, dependencies, "
            "model availability, and hardware compatibility."
        ) from exc

    return _PADDLEOCR_PIPELINE


def _render_pdf_page(page: fitz.Page, dpi: int) -> Image.Image:
    """Render one PDF page as an RGB image."""
    scale = dpi / 72

    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(scale, scale),
        colorspace=fitz.csRGB,
        alpha=False,
    )

    return Image.frombytes(
        "RGB",
        (pixmap.width, pixmap.height),
        pixmap.samples,
    )


def _extract_text_from_result(result) -> str:
    """
    Extract readable text from a PaddleOCR-VL result if Markdown
    export is unavailable.
    """
    result_data = getattr(result, "json", None)

    if callable(result_data):
        result_data = result_data()

    if not isinstance(result_data, dict):
        return ""

    # PaddleOCR result structures may differ between versions.
    # Prefer recognized text or Markdown-related fields.
    preferred_keys = (
        "markdown",
        "markdown_text",
        "text",
        "block_content",
        "content",
    )

    def search(value):
        if isinstance(value, dict):
            for key in preferred_keys:
                candidate = value.get(key)

                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()

            for child in value.values():
                found = search(child)
                if found:
                    return found

        elif isinstance(value, list):
            parts = []

            for child in value:
                found = search(child)
                if found:
                    parts.append(found)

            return "\n\n".join(parts)

        return ""

    return search(result_data)


def _paddleocr_page(image: Image.Image) -> tuple[str, dict]:
    """
    Run PaddleOCR-VL 1.6 on one page and return extracted text
    together with processing metadata.

    PaddleOCR-VL does not provide the same word-confidence scores
    used by the previous Tesseract implementation.
    """
    pipeline = _get_paddleocr_pipeline()

    try:
        with tempfile.TemporaryDirectory(prefix="paddleocr_page_") as temp_dir:
            temp_path = Path(temp_dir)
            image_path = temp_path / "input.png"
            output_dir = temp_path / "output"
            output_dir.mkdir(parents=True, exist_ok=True)

            # Save the image because PaddleOCR-VL accepts a local
            # image path as input.
            image.convert("RGB").save(image_path, format="PNG")

            predictions = pipeline.predict(str(image_path))
            extracted_parts = []

            for prediction in predictions:
                # The official API supports Markdown export.
                try:
                    prediction.save_to_markdown(
                        save_path=str(output_dir)
                    )

                    markdown_files = sorted(output_dir.rglob("*.md"))

                    for markdown_file in markdown_files:
                        content = markdown_file.read_text(
                            encoding="utf-8"
                        ).strip()

                        if content:
                            extracted_parts.append(content)

                    # Avoid adding the same result twice.
                    if extracted_parts:
                        continue

                except Exception:
                    # Fall back to the structured result if Markdown
                    # export fails.
                    pass

                fallback_text = _extract_text_from_result(prediction)

                if fallback_text:
                    extracted_parts.append(fallback_text)

            text = "\n\n".join(extracted_parts).strip()

            metadata = {
                "engine": OCR_ENGINE_NAME,
                "orientation_classification": True,
                "document_unwarping": True,
                "layout_detection": True,
                "chart_recognition": True,
                "seal_recognition": True,
                "output_format": "markdown",
                "confidence": None,
            }

            return text, metadata

    except (PaddleOCRUnavailableError, OCRProcessingError):
        raise

    except Exception as exc:
        raise OCRProcessingError(
            "PaddleOCR-VL failed to process the document page."
        ) from exc


def _base_result(
    document_id: str,
    filename: str,
    file_type: str,
    document_classification: str,
    page_count: int,
    dpi: int | None,
) -> dict:
    """Create the standard OCR result structure."""
    return {
        "document_id": document_id,
        "filename": filename,
        "document_type": (
            "pdf" if file_type == "application/pdf" else "image"
        ),
        "document_classification": document_classification,
        "ocr_engine": OCR_ENGINE_NAME,
        "ocr_required": True,
        "ocr_status": "failed",
        "page_count": page_count,
        "pages": [],
        "average_confidence": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "processing_metadata": {
            "render_dpi": dpi,
            "preprocessing": {
                "engine": OCR_ENGINE_NAME,
                "orientation_classification": True,
                "document_unwarping": True,
                "layout_detection": True,
            },
            "confidence_calculation": (
                "Not available: PaddleOCR-VL does not provide "
                "Tesseract-compatible word-confidence scores. "
                "Use ground-truth evaluation to measure OCR accuracy."
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
    """Build a consistent result for failed OCR processing."""
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
    """Atomically save OCR output as data/ocr/{document_id}.json."""
    os.makedirs(OCR_RESULTS_DIR, exist_ok=True)

    result_path = os.path.join(
        OCR_RESULTS_DIR,
        f"{result['document_id']}.json",
    )

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

            json.dump(
                result,
                temporary_file,
                ensure_ascii=False,
                indent=2,
            )

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
    """
    Process scanned PDFs and images using PaddleOCR-VL 1.6.

    Digital PDFs are returned as not requiring OCR so that the
    existing direct text-extraction workflow can handle them.
    """
    if file_type not in {"application/pdf", *SUPPORTED_IMAGE_TYPES}:
        raise InvalidOCRDocumentError(
            "OCR supports PDF, PNG, JPG, and JPEG files only."
        )

    dpi = None
    document = None
    image = None

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
            document = None

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
        # Initialize the model before processing pages.
        _get_paddleocr_pipeline()

        if file_type in SUPPORTED_IMAGE_TYPES:
            try:
                with Image.open(file_path) as source:
                    image = ImageOps.exif_transpose(source).convert("RGB")

            except (UnidentifiedImageError, OSError, ValueError) as exc:
                raise InvalidOCRDocumentError(
                    "The uploaded image is invalid or could not be read."
                ) from exc

            text, page_metadata = _paddleocr_page(image)

            result["pages"].append(
                {
                    "page_number": 1,
                    "text": text,
                    "confidence": None,
                    "preprocessing": page_metadata,
                }
            )

        else:
            # Process each scanned PDF page individually to preserve
            # the existing page-by-page result structure.
            for page_number, page in enumerate(document, start=1):
                image = _render_pdf_page(page, dpi)

                try:
                    text, page_metadata = _paddleocr_page(image)

                finally:
                    image.close()
                    image = None

                result["pages"].append(
                    {
                        "page_number": page_number,
                        "text": text,
                        "confidence": None,
                        "preprocessing": page_metadata,
                    }
                )

        if not any(page["text"] for page in result["pages"]):
            result["error_message"] = (
                "PaddleOCR-VL completed processing but did not "
                "return any recognizable text."
            )
            return result

        result["ocr_status"] = "completed"

        # PaddleOCR-VL does not expose the same confidence values
        # as Tesseract. Do not fabricate a confidence percentage.
        result["average_confidence"] = None

        return result

    except (
        PaddleOCRUnavailableError,
        InvalidOCRDocumentError,
        OCRProcessingError,
    ):
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
