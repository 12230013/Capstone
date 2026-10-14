"""PaddleOCR-VL 1.6 for scanned PDFs and supported image documents with dynamic device selection and confidence checking."""

import json
import os
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import torch

import fitz
from PIL import Image, ImageOps, UnidentifiedImageError

from app.ocr.config import OCR_RENDER_DPI, OCR_RESULTS_DIR
from app.ocr.document_detection import (
    InvalidPDFError,
    classify_page_texts,
    open_pdf_document,
)

from app.ocr.document_postprocessing import clean_text_for_rag

SUPPORTED_IMAGE_TYPES = {
    "image/png",
    "image/jpeg",
}

MAX_RENDER_DPI = 600
OCR_ENGINE_NAME = "paddleocr-vl-1.6"
CONFIDENCE_THRESHOLD = 0.65  # Threshold below which documents are flagged for human review

# Load the large model only once per Python process.
_PADDLEOCR_PIPELINE = None


class PaddleOCRUnavailableError(RuntimeError):
    """Raised when PaddleOCR-VL cannot be loaded."""


class InvalidOCRDocumentError(ValueError):
    """Raised for unreadable PDFs or invalid image documents."""


class OCRProcessingError(RuntimeError):
    """Raised when PaddleOCR-VL fails to process a readable document."""


def _get_optimal_device() -> str:
    return "cpu"  # Force CPU to test if MPS is causing the crash


def _configured_dpi() -> int:
    """Validate the resolution used to render scanned PDF pages."""
    if not 72 <= OCR_RENDER_DPI <= MAX_RENDER_DPI:
        raise OCRProcessingError(
            f"OCR_RENDER_DPI must be between 72 and {MAX_RENDER_DPI}."
        )
    return OCR_RENDER_DPI


def _get_paddleocr_pipeline():
    """Initialize PaddleOCR-VL 1.6 once and reuse it with optimal hardware device."""
    global _PADDLEOCR_PIPELINE

    if _PADDLEOCR_PIPELINE is not None:
        return _PADDLEOCR_PIPELINE

    device = _get_optimal_device()

    try:
        from paddleocr import PaddleOCRVL

        _PADDLEOCR_PIPELINE = PaddleOCRVL(
            pipeline_version="v1.6",
            device=device,
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


def _estimate_vlm_confidence(text: str, image: Image.Image) -> float:
    """
    Heuristic confidence estimator for Vision-Language Model outputs.
    Since VLMs don't output word-level probabilities, this evaluates 
    extracted text yield relative to image dimensions and character variety.
    """
    if not text or not text.strip():
        return 0.0

    cleaned_text = text.strip()
    char_count = len(cleaned_text)
    
    # Check for repetitive hallucination loops (common failure mode of small VLMs)
    words = cleaned_text.split()
    if len(words) > 10:
        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.2:  # High repetition indicates hallucination
            return 0.30

    # Estimate expected character density based on image resolution
    total_pixels = image.width * image.height
    expected_density_factor = min(1.0, char_count / (total_pixels / 15000))
    
    # Base confidence calculation mapped between 0.4 and 0.95
    base_confidence = min(0.95, max(0.40, 0.50 + (expected_density_factor * 0.4)))
    return round(base_confidence, 2)


def _extract_text_from_result(result) -> str:
    """Extract readable text from a PaddleOCR-VL result if Markdown export is unavailable."""
    result_data = getattr(result, "json", None)

    if callable(result_data):
        result_data = result_data()

    if not isinstance(result_data, dict):
        return ""

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


def _paddleocr_page(image: Image.Image) -> tuple[str, float, dict]:
    """Run PaddleOCR-VL 1.6 on one page, extracting text, confidence, and metadata."""
    pipeline = _get_paddleocr_pipeline()

    try:
        with tempfile.TemporaryDirectory(prefix="paddleocr_page_") as temp_dir:
            temp_path = Path(temp_dir)
            image_path = temp_path / "input.png"
            output_dir = temp_path / "output"
            output_dir.mkdir(parents=True, exist_ok=True)

            image.convert("RGB").save(image_path, format="PNG")

            predictions = pipeline.predict(str(image_path))
            extracted_parts = []

            for prediction in predictions:
                try:
                    prediction.save_to_markdown(save_path=str(output_dir))
                    markdown_files = sorted(output_dir.rglob("*.md"))

                    for markdown_file in markdown_files:
                        content = markdown_file.read_text(encoding="utf-8").strip()
                        if content:
                            extracted_parts.append(content)

                    if extracted_parts:
                        continue
                except Exception:
                    pass

                fallback_text = _extract_text_from_result(prediction)
                if fallback_text:
                    extracted_parts.append(fallback_text)

            text = clean_text_for_rag("\n\n".join(extracted_parts).strip())
            confidence = _estimate_vlm_confidence(text, image)

            metadata = {
                "engine": OCR_ENGINE_NAME,
                "device": _get_optimal_device(),
                "orientation_classification": True,
                "document_unwarping": True,
                "layout_detection": True,
                "chart_recognition": True,
                "seal_recognition": True,
                "output_format": "markdown",
                "estimated_confidence": confidence,
            }

            return text, confidence, metadata

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
        "document_type": ("pdf" if file_type == "application/pdf" else "image"),
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
            "device": _get_optimal_device(),
            "preprocessing": {
                "engine": OCR_ENGINE_NAME,
                "orientation_classification": True,
                "document_unwarping": True,
                "layout_detection": True,
            },
            "confidence_calculation": (
                "Heuristic VLM confidence estimation evaluating text yield, "
                "character variety, and spatial density."
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
    """Process scanned PDFs and images using PaddleOCR-VL 1.6 with confidence checking."""
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
            page_texts = [page.get_text("text", sort=True) for page in document]
            detection = classify_page_texts(page_texts)
        except (InvalidPDFError, fitz.FileDataError, ValueError, RuntimeError) as exc:
            if document is not None:
                document.close()
            raise InvalidOCRDocumentError("The PDF is invalid or could not be read.") from exc

        if detection["classification"] == "digital_pdf":
            document.close()
            return {
                "document_id": document_id,
                "document_type": "pdf",
                "document_classification": "digital_pdf",
                "ocr_required": False,
                "ocr_status": "not_required",
                "extraction_method": "direct",
                "message": f"This PDF contains selectable text. Use POST /documents/{document_id}/extract instead.",
            }

        document_classification = "scanned_pdf"
        page_count = detection["page_count"]
        dpi = _configured_dpi()
    else:
        document_classification = "image"
        page_count = 1

    result = _base_result(document_id, filename, file_type, document_classification, page_count, dpi)

    try:
        _get_paddleocr_pipeline()
        page_confidences = []

        if file_type in SUPPORTED_IMAGE_TYPES:
            try:
                with Image.open(file_path) as source:
                    image = ImageOps.exif_transpose(source).convert("RGB")
            except (UnidentifiedImageError, OSError, ValueError) as exc:
                raise InvalidOCRDocumentError("The uploaded image is invalid or could not be read.") from exc

            text, confidence, page_metadata = _paddleocr_page(image)
            page_confidences.append(confidence)

            result["pages"].append({
                "page_number": 1,
                "text": text,
                "confidence": confidence,
                "preprocessing": page_metadata,
            })
        else:
            for page_number, page in enumerate(document, start=1):
                image = _render_pdf_page(page, dpi)
                try:
                    text, confidence, page_metadata = _paddleocr_page(image)
                    page_confidences.append(confidence)
                finally:
                    image.close()
                    image = None

                result["pages"].append({
                    "page_number": page_number,
                    "text": text,
                    "confidence": confidence,
                    "preprocessing": page_metadata,
                })

        if not any(page["text"] for page in result["pages"]):
            result["error_message"] = "PaddleOCR-VL completed processing but did not return any recognizable text."
            result["ocr_status"] = "failed"
            return result

        # Compute average confidence across pages
        avg_confidence = round(statistics.mean(page_confidences), 2) if page_confidences else 0.0
        result["average_confidence"] = avg_confidence

        # Confidence checking & routing branch (High vs Low confidence / Human review)
        if avg_confidence < CONFIDENCE_THRESHOLD:
            result["ocr_status"] = "needs_human_review"
            result["review_reason"] = (
                f"Average confidence score ({avg_confidence}) is below the threshold ({CONFIDENCE_THRESHOLD}). "
                "Routed to secondary review queue."
            )
        else:
            result["ocr_status"] = "completed"

        return result

    except (PaddleOCRUnavailableError, InvalidOCRDocumentError, OCRProcessingError):
        raise
    except (fitz.FileDataError, ValueError, RuntimeError) as exc:
        raise InvalidOCRDocumentError("The document could not be rendered or read.") from exc
    finally:
        if image is not None:
            image.close()
        if document is not None:
            document.close()