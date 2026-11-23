"""Configured page-level OCR adapters for Tesseract and PaddleOCR engines."""

from app.ocr.layout import pdf_blocks, ocr_blocks, blocks_text, LAYOUT_VERSION

import importlib
import json
import logging
import math
import os
import statistics
import tempfile
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz
from PIL import Image, ImageOps, UnidentifiedImageError

from app.ocr.config import (
    OCR_ENGINE,
    OCR_MODEL_ID,
    OCR_RENDER_DPI,
    OCR_RESULTS_DIR,
    PADDLE_DEVICE,
    PADDLE_VL_BACKEND,
    PADDLE_LAYOUT_MODEL_DIR,
    PADDLEOCR_DEVICE,
    PADDLEOCR_MOBILE_DET_MODEL_DIR,
    PADDLEOCR_MOBILE_REC_MODEL_DIR,
    PADDLEOCR_PREPROCESSING_ENABLED,
    PADDLEOCR_VARIANT,
    PADDLE_VL_MODEL_DIR,
    TESSERACT_CMD,
)
from app.ocr.document_detection import (
    InvalidPDFError,
    classify_page_texts,
    normalize_detection_text,
    open_pdf_document,
    page_image_coverage,
    page_text_area_coverage,
)
from app.ocr.document_preprocessing import (
    ImagePreprocessingError,
    preprocess_image,
    preprocessing_settings,
)
from app.ocr.engine_adapters import OCRPageAdapter
from app.ocr.timing import timed_ocr_stage

SUPPORTED_IMAGE_TYPES = {
    "image/png",
    "image/jpeg",
}
MAX_RENDER_DPI = 600
MIN_PAGE_CONFIDENCE = float(os.getenv("OCR_MIN_PAGE_CONFIDENCE", "50"))
logger = logging.getLogger(__name__)


class _LazyTesseractModule:
    def __getattr__(self, name: str) -> Any:
        module = importlib.import_module("pytesseract")
        return getattr(module, name)


pytesseract = _LazyTesseractModule()


class OCREngineUnavailableError(RuntimeError):
    """Raised when the selected OCR engine cannot be initialized."""


class TesseractUnavailableError(OCREngineUnavailableError):
    """Raised when the Tesseract application cannot be found or started."""


class InvalidOCRDocumentError(ValueError):
    """Raised for unreadable PDFs or invalid image documents."""


class OCRProcessingError(RuntimeError):
    """Raised when the selected OCR engine fails on a readable image."""


def _configured_dpi() -> int:
    if not 72 <= OCR_RENDER_DPI <= MAX_RENDER_DPI:
        raise OCRProcessingError(
            f"OCR_RENDER_DPI must be between 72 and {MAX_RENDER_DPI}"
        )
    return OCR_RENDER_DPI


def _configured_min_confidence() -> float:
    if not 0 <= MIN_PAGE_CONFIDENCE <= 100:
        raise OCRProcessingError("OCR_MIN_PAGE_CONFIDENCE must be between 0 and 100")
    return MIN_PAGE_CONFIDENCE


def _ensure_tesseract_available() -> None:
    try:
        implementation = importlib.import_module("pytesseract.pytesseract")
    except ImportError as exc:
        raise TesseractUnavailableError(
            "The pytesseract package is not installed."
        ) from exc
    if TESSERACT_CMD:
        implementation.tesseract_cmd = TESSERACT_CMD
    try:
        pytesseract.get_tesseract_version()
    except (implementation.TesseractNotFoundError, FileNotFoundError) as exc:
        raise TesseractUnavailableError(
            "Tesseract is not installed or could not be found. Install the "
            "Tesseract executable and set TESSERACT_CMD if it is not on PATH."
        ) from exc
    except implementation.TesseractError as exc:
        raise TesseractUnavailableError(
            "Tesseract is installed but could not be started."
        ) from exc


def create_paddle_engine(
    layout_model_dir: str | None,
    vl_model_dir: str | None,
    device: str,
) -> Any:
    paddle_adapter = importlib.import_module("app.ocr.paddle_ocr")
    return paddle_adapter.PaddleOCRVLEngine(
        layout_model_dir,
        vl_model_dir,
        device=device,
    )


def _create_paddle_engine() -> Any:
    paddle_adapter = importlib.import_module("app.ocr.paddle_ocr")
    try:
        engine = create_paddle_engine(
            PADDLE_LAYOUT_MODEL_DIR,
            PADDLE_VL_MODEL_DIR,
            PADDLE_DEVICE,
        )
        engine.initialize()
        return engine
    except paddle_adapter.PaddleEngineUnavailableError as exc:
        raise OCREngineUnavailableError(str(exc)) from exc


CLASSIC_PADDLE_MODEL_NAMES = {
    "mobile": ("PP-OCRv5_mobile_det", "en_PP-OCRv5_mobile_rec"),
}


def _require_classic_model_directory(path_value: str | None, label: str) -> str:
    if not path_value:
        raise OCREngineUnavailableError(
            f"classic_paddle_{label}_model_directory_not_configured"
        )
    model_dir = Path(path_value).expanduser()
    if not model_dir.is_dir() or not all(
        (model_dir / name).is_file()
        for name in ("inference.yml", "inference.pdiparams")
    ):
        raise OCREngineUnavailableError(
            f"classic_paddle_{label}_model_directory_invalid"
        )
    return str(model_dir.resolve())


def create_classic_paddle_engine(
    variant: str,
    detection_model_dir: str | None,
    recognition_model_dir: str | None,
    device: str,
) -> Any:
    model_names = CLASSIC_PADDLE_MODEL_NAMES.get(variant)
    if model_names is None:
        raise OCREngineUnavailableError("classic_paddle_variant_unsupported")
    detection_dir = _require_classic_model_directory(
        detection_model_dir,
        "detection",
    )
    recognition_dir = _require_classic_model_directory(
        recognition_model_dir,
        "recognition",
    )
    try:
        paddleocr_module = importlib.import_module("paddleocr")
    except ImportError as exc:
        raise OCREngineUnavailableError(
            "classic_paddleocr_dependency_unavailable"
        ) from exc
    return paddleocr_module.PaddleOCR(
        text_detection_model_name=model_names[0],
        text_detection_model_dir=detection_dir,
        text_recognition_model_name=model_names[1],
        text_recognition_model_dir=recognition_dir,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        device=device,
        enable_mkldnn=False,
    )


def _create_classic_paddle_engine() -> Any:
    return create_classic_paddle_engine(
        PADDLEOCR_VARIANT,
        PADDLEOCR_MOBILE_DET_MODEL_DIR,
        PADDLEOCR_MOBILE_REC_MODEL_DIR,
        PADDLEOCR_DEVICE,
    )


def _paddle_pipeline_version() -> str:
    paddle_adapter = importlib.import_module("app.ocr.paddle_ocr")
    return paddle_adapter.PADDLE_PIPELINE_VERSION


def _preprocess_and_paddle_page(
    image: Image.Image, engine: Any, source_page_number: int, correlation_id: str,
) -> tuple[str, None, list[float], dict[str, Any]]:
    paddle_adapter = importlib.import_module("app.ocr.paddle_ocr")
    from app.ocr.table_geometry import ruled_cells
    source, regions = ruled_cells(image)
    ocr_image = source
    preprocessing = preprocessing_settings()
    image_path = None
    try:
        try:
            ocr_image, preprocessing = preprocess_image(source, allow_deskew=not bool(regions))
            preprocessing["selection"] = "preprocessed" if ocr_image is not source else "original_rgb"
        except ImagePreprocessingError:
            preprocessing["selection"] = "original_rgb_fallback"
            preprocessing["fallback_reason"] = "preprocessing_failed"
        preprocessing["table_geometry_source"] = "original_image"
        preprocessing["layout_deskew_applied"] = source is not image
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as image_file:
            image_path = image_file.name
        ocr_image.save(image_path, format="PNG")
        with timed_ocr_stage(logger, "paddle_vl_prediction", correlation_id,
                             page_number=source_page_number,
                             device="metal" if PADDLE_VL_BACKEND == "mlx-vlm-server" else PADDLE_DEVICE,
                             layout_device=PADDLE_DEVICE, recognition_backend=PADDLE_VL_BACKEND):
            page = engine.predict_page(image_path, source_page_number,
                correlation_id=correlation_id, image_width=ocr_image.width,
                image_height=ocr_image.height, table_regions=regions)
        preprocessing["blocks"] = page["blocks"]
        return page["text"], None, [], preprocessing
    except paddle_adapter.PaddleOutputSchemaError as exc:
        raise OCRProcessingError("PaddleOCR-VL returned an invalid page layout.") from exc
    except paddle_adapter.PaddleInferenceError as exc:
        raise OCRProcessingError(str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise OCRProcessingError("The image could not be prepared for PaddleOCR-VL.") from exc
    finally:
        if image_path and os.path.exists(image_path): os.remove(image_path)
        if ocr_image is not image: ocr_image.close()
        if source is not image and source is not ocr_image: source.close()


def _classic_paddle_page_output(outputs: Any) -> tuple[str, float | None, list[float]]:
    """Average valid non-empty line scores as a 0-100 page confidence."""
    if not isinstance(outputs, (list, tuple)) or len(outputs) != 1:
        raise OCRProcessingError(
            "Classic PaddleOCR returned an unexpected page result count."
        )
    output = outputs[0]
    if not isinstance(output, dict):
        raise OCRProcessingError("Classic PaddleOCR returned an invalid page result.")
    raw_texts = output.get("rec_texts")
    raw_scores = output.get("rec_scores")
    if isinstance(raw_texts, (str, bytes)) or isinstance(raw_scores, (str, bytes)):
        raise OCRProcessingError(
            "Classic PaddleOCR returned invalid recognition fields."
        )
    try:
        texts = list(raw_texts)
        scores = list(raw_scores)
    except TypeError as exc:
        raise OCRProcessingError(
            "Classic PaddleOCR returned invalid recognition fields."
        ) from exc
    if len(texts) != len(scores) or any(not isinstance(text, str) for text in texts):
        raise OCRProcessingError(
            "Classic PaddleOCR returned misaligned recognition fields."
        )

    confidence_values = []
    for text, value in zip(texts, scores):
        if not text.strip():
            continue
        try:
            score = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(score) and 0 <= score <= 1:
            confidence_values.append(score * 100)
    confidence = (
        round(statistics.mean(confidence_values), 1)
        if confidence_values
        else None
    )
    return "\n".join(text.strip() for text in texts if text.strip()), confidence, confidence_values


def _preprocess_and_classic_paddle_page(
    image: Image.Image,
    engine: Any,
    source_page_number: int,
    correlation_id: str,
) -> tuple[str, float | None, list[float], dict[str, Any]]:
    # Preserve faint physical rules before filtering. All cell coordinates and
    # recognition pixels must use the same aligned image frame.
    from app.ocr.table_geometry import ruled_cells
    source_image, regions = ruled_cells(image)
    preprocessing = _classic_paddle_preprocessing_settings()
    if PADDLEOCR_PREPROCESSING_ENABLED:
        try:
            with timed_ocr_stage(
                logger,
                "page_preprocessing",
                correlation_id,
                page_number=source_page_number,
                image_width=image.width,
                image_height=image.height,
            ):
                ocr_image, preprocessing = preprocess_image(source_image, allow_deskew=not bool(regions))
            preprocessing["selection"] = (
                "preprocessed" if ocr_image is not source_image else "original_rgb"
            )
        except ImagePreprocessingError:
            logger.warning(
                "OCR preprocessing failed; using original RGB image",
                extra={
                    "correlation_id": correlation_id,
                    "page_number": source_page_number,
                    "event": "classic_paddle_preprocessing_fallback",
                },
            )
            ocr_image = source_image
            preprocessing["selection"] = "original_rgb_fallback"
            preprocessing["fallback_reason"] = "preprocessing_failed"
    else:
        ocr_image = source_image
        preprocessing["selection"] = "original_rgb"

    preprocessing["layout_deskew_applied"] = source_image is not image
    preprocessing["table_geometry_source"] = "original_image"
    image_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as image_file:
            image_path = image_file.name
        ocr_image.save(image_path, format="PNG")
        with timed_ocr_stage(
            logger,
            "classic_paddle_prediction",
            correlation_id,
            page_number=source_page_number,
            device=PADDLEOCR_DEVICE,
            image_width=ocr_image.width,
            image_height=ocr_image.height,
        ):
            outputs = engine.predict(image_path)
        text, confidence, confidence_values = _classic_paddle_page_output(outputs)
        try:
            def read_cells(crops):
                import numpy as np
                readings = []
                for start in range(0, len(crops), 24):
                    batch = [np.asarray(crop)[:, :, ::-1].copy() for crop in crops[start:start+24]]
                    predictions = list(engine.predict(batch))
                    for prediction in predictions:
                        cell_text, cell_confidence, _ = _classic_paddle_page_output([prediction])
                        readings.append({"text":cell_text.replace("\n", " "),"confidence":cell_confidence})
                return readings
            preprocessing["blocks"] = ocr_blocks(outputs[0], ocr_image, regions=regions, cell_reader=read_cells)
        except (ValueError, TypeError, KeyError, IndexError, RuntimeError):
            logger.warning("Layout detection unavailable; retaining recognized text", exc_info=True)
        return text, confidence, confidence_values, preprocessing
    except (OSError, ValueError) as exc:
        raise OCRProcessingError(
            "The page image could not be prepared for classic PaddleOCR."
        ) from exc
    finally:
        if image_path and os.path.exists(image_path):
            os.remove(image_path)
        if ocr_image is not image:
            ocr_image.close()
        if source_image is not image and source_image is not ocr_image:
            source_image.close()


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


def _classic_paddle_preprocessing_settings() -> dict[str, Any]:
    settings = preprocessing_settings()
    if not PADDLEOCR_PREPROCESSING_ENABLED:
        settings.update(
            {
                "enabled": False,
                "grayscale": False,
                "denoise": False,
                "contrast": False,
                "threshold": False,
                "deskew": False,
            }
        )
    return settings


def _ocr_page(image: Image.Image) -> tuple[str, float | None, list[float]]:
    try:
        implementation = importlib.import_module("pytesseract.pytesseract")
        output = importlib.import_module("pytesseract").Output
    except ImportError as exc:
        raise TesseractUnavailableError(
            "The pytesseract package is not installed."
        ) from exc
    try:
        text = pytesseract.image_to_string(image)
        data = pytesseract.image_to_data(image, output_type=output.DICT)
    except (implementation.TesseractNotFoundError, FileNotFoundError) as exc:
        raise TesseractUnavailableError(
            "Tesseract is not installed or could not be found. Install the "
            "Tesseract executable and set TESSERACT_CMD if it is not on PATH."
        ) from exc
    except implementation.TesseractError as exc:
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


class TesseractPageAdapter:
    name = "tesseract"

    def initialize(self) -> None:
        _ensure_tesseract_available()

    def process_page(
        self,
        image: Image.Image,
        page_number: int,
        correlation_id: str,
    ) -> tuple[str, float | None, list[float], dict[str, Any]]:
        return _preprocess_and_ocr_page(image, correlation_id, page_number)


class PaddleOCRVLPageAdapter:
    name = "paddleocr_vl"

    def __init__(self) -> None:
        self.engine: Any | None = None

    def initialize(self) -> None:
        self.engine = _create_paddle_engine()

    def process_page(
        self,
        image: Image.Image,
        page_number: int,
        correlation_id: str,
    ) -> tuple[str, None, list[float], dict[str, Any]]:
        if self.engine is None:
            raise OCRProcessingError(
                "PaddleOCR-VL was not initialized for this document."
            )
        return _preprocess_and_paddle_page(
            image,
            self.engine,
            page_number,
            correlation_id,
        )


class ClassicPaddleOCRPageAdapter:
    name = "paddleocr"

    def __init__(self) -> None:
        self.engine: Any | None = None

    def initialize(self) -> None:
        self.engine = _create_classic_paddle_engine()

    def process_page(
        self,
        image: Image.Image,
        page_number: int,
        correlation_id: str,
    ) -> tuple[str, float | None, list[float], dict[str, Any]]:
        if self.engine is None:
            raise OCRProcessingError(
                "Classic PaddleOCR was not initialized for this document."
            )
        return _preprocess_and_classic_paddle_page(
            image,
            self.engine,
            page_number,
            correlation_id,
        )


def _create_ocr_adapter(engine_name: str) -> OCRPageAdapter:
    if engine_name == "tesseract":
        return TesseractPageAdapter()
    if engine_name == "paddleocr_vl":
        return PaddleOCRVLPageAdapter()
    if engine_name == "paddleocr":
        return ClassicPaddleOCRPageAdapter()
    raise OCRProcessingError("The configured OCR engine is unsupported.")


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
    correlation_id: str,
    page_number: int,
) -> tuple[str, float | None, list[float], dict[str, Any]]:
    try:
        with timed_ocr_stage(
            logger,
            "page_preprocessing",
            correlation_id,
            page_number=page_number,
            image_width=image.width,
            image_height=image.height,
        ):
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
    confidence_calculation = {
        "paddleocr_vl": "PaddleOCR-VL confidence is unavailable and remains null.",
        "paddleocr": (
            "Arithmetic mean of valid per-line recognition scores for non-empty "
            "lines, converted from [0, 1] to [0, 100]; null when none are valid."
        ),
        "tesseract": (
            "Arithmetic mean of non-negative Tesseract word confidences; "
            "null when Tesseract provides none."
        ),
    }[OCR_ENGINE]
    has_confidence = OCR_ENGINE != "paddleocr_vl"
    return {
        "document_id": document_id,
        "layout_version": LAYOUT_VERSION,
        "filename": filename,
        "document_type": "pdf" if file_type == "application/pdf" else "image",
        "document_classification": document_classification,
        "ocr_engine": OCR_ENGINE,
        "ocr_model": OCR_MODEL_ID,
        "ocr_required": True,
        "ocr_status": "failed",
        "page_count": page_count,
        "pages": [],
        "average_confidence": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "processing_metadata": {
            "render_dpi": dpi,
            "preprocessing": (
                _classic_paddle_preprocessing_settings()
                if OCR_ENGINE == "paddleocr"
                else preprocessing_settings()
            ),
            "confidence_calculation": confidence_calculation,
            "confidence_available": has_confidence,
            "minimum_page_confidence": (
                MIN_PAGE_CONFIDENCE if has_confidence else None
            ),
            "vl_recognition_backend": PADDLE_VL_BACKEND if OCR_ENGINE == "paddleocr_vl" else None,
            "paddle_pipeline_version": (
                _paddle_pipeline_version() if OCR_ENGINE == "paddleocr_vl" else None
            ),
            "paddle_device": (
                PADDLE_DEVICE
                if OCR_ENGINE == "paddleocr_vl"
                else (PADDLEOCR_DEVICE if OCR_ENGINE == "paddleocr" else None)
            ),
            "paddleocr_variant": (
                PADDLEOCR_VARIANT if OCR_ENGINE == "paddleocr" else None
            ),
            "selection_rule": (
                "PP-OCRv5 Mobile recognition scores are not an accuracy measure; "
                "all PaddleOCR output requires manual review and is not automatically "
                "indexed."
                if OCR_ENGINE == "paddleocr"
                else (
                    "PaddleOCR-VL confidence is unavailable; OCR output is retained "
                    "for manual review and is not automatically indexed."
                    if OCR_ENGINE == "paddleocr_vl"
                    else (
                        "Use OCR fallback text only when OCR returns non-empty text "
                        "with mean engine confidence at or above the configured minimum; "
                        "otherwise retain available embedded text and require manual "
                        "review."
                    )
                )
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


def load_ocr_result(
    document_id: str,
    expected_engine: str | None = None,
    expected_model: str | None = None,
) -> dict | None:
    """Load a previously completed OCR result for an indexing retry."""
    result_path = os.path.join(OCR_RESULTS_DIR, f"{document_id}.json")
    try:
        with open(result_path, encoding="utf-8") as result_file:
            result = json.load(result_file)
    except FileNotFoundError:
        return None

    if not isinstance(result, dict) or result.get("document_id") != document_id:
        raise ValueError("Saved OCR result does not match the requested document.")
    if result.get("ocr_status") != "completed":
        return None
    if expected_engine is not None and result.get("ocr_engine") != expected_engine:
        return None
    if expected_model is not None and result.get("ocr_model") != expected_model:
        return None

    pages = result.get("pages")
    if not isinstance(pages, list) or any(
        not isinstance(page, dict)
        or not isinstance(page.get("page_number"), int)
        or isinstance(page.get("page_number"), bool)
        or page.get("page_number") < 1
        or not isinstance(page.get("text"), str)
        for page in pages
    ):
        raise ValueError("Saved OCR result contains invalid page data.")
    return result


def run_document_ocr(
    file_path: str,
    document_id: str,
    filename: str,
    file_type: str,
    correlation_id: str | None = None,
) -> dict:
    """Select direct extraction or OCR per PDF page and flag uncertain results."""
    correlation_id = correlation_id or document_id
    if file_type not in {"application/pdf", *SUPPORTED_IMAGE_TYPES}:
        raise InvalidOCRDocumentError("OCR supports PDF, PNG, JPG, and JPEG files only.")

    dpi = None
    document = None
    if file_type == "application/pdf":
        with timed_ocr_stage(
            logger,
            "pdf_extraction_and_classification",
            correlation_id,
        ) as extraction_fields:
            try:
                document = open_pdf_document(file_path)
                page_texts = [
                    page.get_text("text", sort=True)
                    for page in document
                ]
                image_coverages = [page_image_coverage(page) for page in document]
                text_coverages = [page_text_area_coverage(page) for page in document]
                detection = classify_page_texts(
                    page_texts,
                    image_coverages=image_coverages,
                    text_coverages=text_coverages,
                )
                extraction_fields["page_count"] = detection["page_count"]
                extraction_fields["classification"] = detection["classification"]
                extraction_fields["ocr_required"] = detection["ocr_required"]
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

        if detection["quality_decision"] == "direct_extraction_accepted":
            result = _base_result(
                document_id,
                filename,
                file_type,
                "digital_pdf",
                detection["page_count"],
                None,
            )
            result.update(
                {
                    "ocr_required": False,
                    "ocr_status": "not_required",
                    "extraction_method": "direct",
                    "quality_decision": "direct_extraction_accepted",
                    "page_decisions": detection["page_decisions"],
                    "pages": [
                        {
                            "page_number": page_number,
                            "text": page_text.strip(),
                            "extraction_method": "direct",
                            "quality_decision": "direct_extraction_accepted",
                        }
                        for page_number, page_text in enumerate(page_texts, start=1)
                    ],
                }
            )
            for item, source_page in zip(result["pages"], document):
                item["raw_text"] = item["text"]
                item["blocks"] = pdf_blocks(source_page)
                if item["blocks"]:
                    item["text"] = blocks_text(item["blocks"])
            document.close()
            return {
                **result,
                "message": "Direct text extraction passed the configured page quality checks.",
            }
        page_decisions = detection["page_decisions"]
        document_classification = (
            "mixed_pdf"
            if any(
                decision["decision"] == "direct_extraction_accepted"
                for decision in page_decisions
            )
            else "scanned_pdf"
        )
        page_count = detection["page_count"]
        try:
            dpi = _configured_dpi()
        except OCRProcessingError:
            document.close()
            raise
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
    if file_type == "application/pdf":
        result["page_decisions"] = page_decisions
    try:
        minimum_confidence = (
            _configured_min_confidence()
            if OCR_ENGINE != "paddleocr_vl"
            else None
        )
        image = None
        if file_type in SUPPORTED_IMAGE_TYPES:
            try:
                with Image.open(file_path) as source:
                    image = ImageOps.exif_transpose(source).convert("RGB")
            except (UnidentifiedImageError, OSError, ValueError) as exc:
                raise InvalidOCRDocumentError(
                    "The uploaded image is invalid or could not be read."
                ) from exc

        confidence_values = []
        methods = set()
        needs_ocr = file_type != "application/pdf" or any(
            item["decision"] != "direct_extraction_accepted"
            for item in page_decisions
        )
        ocr_adapter: OCRPageAdapter | None = None
        if needs_ocr:
            ocr_adapter = _create_ocr_adapter(OCR_ENGINE)
            if ocr_adapter.name in {"paddleocr", "paddleocr_vl"}:
                device = (
                    PADDLEOCR_DEVICE
                    if ocr_adapter.name == "paddleocr"
                    else PADDLE_DEVICE
                )
                with timed_ocr_stage(
                    logger,
                    "paddle_engine_initialization",
                    correlation_id,
                    device=device,
                ):
                    ocr_adapter.initialize()
            else:
                ocr_adapter.initialize()

        if file_type == "application/pdf":
            for page_number, page in enumerate(document, start=1):
                page_decision = page_decisions[page_number - 1]
                direct_text = page_texts[page_number - 1].strip()
                if page_decision["decision"] == "direct_extraction_accepted":
                    methods.add("direct")
                    result["pages"].append(
                        {
                            "page_number": page_number,
                            "text": direct_text,
                            "confidence": None,
                            "extraction_method": "direct",
                            "quality_decision": "direct_extraction_accepted",
                        }
                    )
                    continue
                with timed_ocr_stage(
                    logger,
                    "pdf_page_rendering",
                    correlation_id,
                    page_number=page_number,
                    dpi=dpi,
                ) as render_fields:
                    image = _render_pdf_page(page, dpi)
                    render_fields["image_width"] = image.width
                    render_fields["image_height"] = image.height
                try:
                    if ocr_adapter is None:
                        raise OCRProcessingError(
                            "OCR adapter was not initialized for this document."
                        )
                    try:
                        (
                            ocr_text,
                            page_confidence,
                            page_confidence_values,
                            page_preprocessing,
                        ) = ocr_adapter.process_page(
                            image,
                            page_number,
                            correlation_id,
                        )
                    except OCRProcessingError:
                        if ocr_adapter.name != "tesseract":
                            raise
                        ocr_text = ""
                        page_confidence = None
                        page_confidence_values = []
                        page_preprocessing = {}
                finally:
                    image.close()
                confidence_values.extend(page_confidence_values)
                if ocr_adapter.name == "paddleocr_vl":
                    if ocr_text:
                        text = ocr_text
                        method = "paddleocr_vl"
                    elif direct_text:
                        text = direct_text
                        method = "direct"
                    else:
                        text = ""
                        method = "paddleocr_vl"
                    quality_decision = "manual_review_recommended"
                elif (
                    bool(ocr_text)
                    and page_confidence is not None
                    and minimum_confidence is not None
                    and page_confidence >= minimum_confidence
                ):
                    text = ocr_text
                    method = ocr_adapter.name
                    quality_decision = "ocr_fallback_recommended"
                elif direct_text:
                    text = direct_text
                    method = "direct"
                    quality_decision = "manual_review_recommended"
                else:
                    text = ocr_text
                    method = ocr_adapter.name
                    quality_decision = "manual_review_recommended"
                if ocr_adapter.name == "paddleocr":
                    quality_decision = "manual_review_recommended"
                methods.add(method)
                similarity = None
                if direct_text and ocr_text:
                    similarity = SequenceMatcher(
                        None,
                        normalize_detection_text(direct_text).casefold(),
                        normalize_detection_text(ocr_text).casefold(),
                    ).ratio()
                result["pages"].append(
                    {
                        "page_number": page_number,
                        "text": text,
                        "confidence": page_confidence,
                        "preprocessing": page_preprocessing,
                        "extraction_method": method,
                        "quality_decision": quality_decision,
                        "direct_ocr_similarity": (
                            round(similarity, 4) if similarity is not None else None
                        ),
                        "quality_warning": (
                            "embedded_and_ocr_text_disagree"
                            if similarity is not None and similarity < 0.25
                            else (
                                "recognition_accuracy_unverified"
                                if ocr_adapter.name == "paddleocr"
                                else None
                            )
                        ),
                    }
                )
        else:
            if ocr_adapter is None:
                raise OCRProcessingError(
                    "OCR adapter was not initialized for this document."
                )
            (
                text,
                page_confidence,
                page_confidence_values,
                page_preprocessing,
            ) = ocr_adapter.process_page(image, 1, correlation_id)
            confidence_values.extend(page_confidence_values)
            methods.add(ocr_adapter.name)
            result["pages"].append(
                {
                    "page_number": 1,
                    "text": text,
                    "confidence": page_confidence,
                    "preprocessing": page_preprocessing,
                    "extraction_method": OCR_ENGINE,
                    "quality_decision": (
                        "manual_review_recommended"
                        if ocr_adapter.name in {"paddleocr", "paddleocr_vl"}
                        else (
                            "ocr_fallback_recommended"
                            if page_confidence is not None
                            and minimum_confidence is not None
                            and page_confidence >= minimum_confidence
                            and text
                            else "manual_review_recommended"
                        )
                    ),
                    "quality_warning": (
                        "recognition_accuracy_unverified"
                        if ocr_adapter.name == "paddleocr"
                        else None
                    ),
                }
            )

        expected_page_numbers = list(range(1, page_count + 1))
        actual_page_numbers = [page.get("page_number") for page in result["pages"]]
        if actual_page_numbers != expected_page_numbers:
            raise OCRProcessingError(
                "OCR output did not match the source document page sequence."
            )
        if not any(page["text"] for page in result["pages"]):
            result["error_message"] = (
                f"{OCR_ENGINE} completed but did not recognize any text."
            )
            result["ocr_status"] = "manual_review"
            result["quality_decision"] = "manual_review_recommended"
            return result

        result["ocr_status"] = "completed"
        result["extraction_method"] = (
            "mixed" if len(methods) > 1 else next(iter(methods), "tesseract")
        )
        result["quality_decision"] = (
            "manual_review_recommended"
            if any(
                page["quality_decision"] == "manual_review_recommended"
                for page in result["pages"]
            )
            else (
                "ocr_fallback_recommended"
                if OCR_ENGINE in methods
                else "direct_extraction_accepted"
            )
        )
        result["average_confidence"] = (
            round(statistics.mean(confidence_values), 1)
            if confidence_values
            else None
        )
        for item in result["pages"]:
            item["raw_text"] = item["text"]
            blocks = item.get("preprocessing", {}).pop("blocks", None)
            if blocks is None and item["extraction_method"] == "direct" and document is not None:
                blocks = pdf_blocks(document[item["page_number"]-1])
            item["blocks"] = blocks or [{"type": "text", "text": item["text"]}]
            item["text"] = blocks_text(item["blocks"])
        return result
    except (
        OCREngineUnavailableError,
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
