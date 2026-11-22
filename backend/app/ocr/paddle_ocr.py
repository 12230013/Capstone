"""Compatibility wrapper for PaddleOCR v5-style runtime access.

This module provides the interface expected by ``app.ocr.document_ocr`` while
remaining tolerant of missing optional dependencies and slow model downloads.
"""

from __future__ import annotations

import importlib
import json
from typing import Any


class PaddleEngineUnavailableError(RuntimeError):
    """Raised when the PaddleOCR runtime cannot be initialized."""


class PaddleInferenceError(RuntimeError):
    """Raised when a PaddleOCR inference attempt fails."""


class PaddleOutputSchemaError(RuntimeError):
    """Raised when inference output cannot be interpreted."""


class PaddleOCRVLEngine:
    """Thin wrapper around the installed PaddleOCR runtime.

    The real backend may expose ``PaddleOCR`` directly or a project-specific
    wrapper. This class normalizes the calls used by the document OCR pipeline.
    """

    PADDLE_PIPELINE_VERSION = "PP-OCRv5-mobile"

    def __init__(
        self,
        layout_model_dir: str | None = None,
        vl_model_dir: str | None = None,
        device: str = "cpu",
    ) -> None:
        self.layout_model_dir = layout_model_dir
        self.vl_model_dir = vl_model_dir
        self.device = device
        self._engine: Any | None = None

    def initialize(self) -> None:
        try:
            paddleocr_module = importlib.import_module("paddleocr")
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise PaddleEngineUnavailableError(
                "The paddleocr package is not installed."
            ) from exc

        kwargs: dict[str, Any] = {
            "device": self.device,
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "enable_mkldnn": False,
        }
        if self.layout_model_dir:
            kwargs["layout_model_dir"] = self.layout_model_dir
        if self.vl_model_dir:
            kwargs["vl_model_dir"] = self.vl_model_dir

        try:
            self._engine = paddleocr_module.PaddleOCR(**kwargs)
        except Exception as exc:  # pragma: no cover - runtime-specific failure
            raise PaddleEngineUnavailableError(
                "PaddleOCR v5 could not be initialized."
            ) from exc

    def predict_page(
        self,
        image_path: str,
        source_page_number: int,
        correlation_id: str | None = None,
        image_width: int | None = None,
        image_height: int | None = None,
    ) -> dict[str, Any]:
        if self._engine is None:
            raise PaddleInferenceError("PaddleOCR-VL engine was not initialized.")

        try:
            result = self._engine.ocr(
                image_path,
                cls=False,
            )
        except TypeError:
            # Some PaddleOCR builds expose a different call signature.
            try:
                result = self._engine.predict(image_path)
            except Exception as exc:  # pragma: no cover - runtime-specific failure
                raise PaddleInferenceError(
                    "PaddleOCR page inference failed."
                ) from exc
        except Exception as exc:  # pragma: no cover - runtime-specific failure
            raise PaddleInferenceError(
                "PaddleOCR page inference failed."
            ) from exc

        text_parts: list[str] = []
        if isinstance(result, list):
            for page_result in result:
                if isinstance(page_result, dict):
                    if isinstance(page_result.get("rec_texts"), list):
                        text_parts.extend(str(item) for item in page_result["rec_texts"])
                        continue
                    if isinstance(page_result.get("text"), str):
                        text_parts.append(page_result["text"])
                elif isinstance(page_result, (list, tuple)):
                    for item in page_result:
                        if isinstance(item, dict) and isinstance(item.get("text"), str):
                            text_parts.append(item["text"])
        elif isinstance(result, dict):
            for key in ("rec_texts", "text"):
                value = result.get(key)
                if isinstance(value, list):
                    text_parts.extend(str(item) for item in value)
                elif isinstance(value, str):
                    text_parts.append(value)
            if not text_parts and "result" in result:
                nested = result["result"]
                if isinstance(nested, list):
                    for item in nested:
                        if isinstance(item, dict):
                            text = item.get("text")
                            if isinstance(text, str):
                                text_parts.append(text)

        text = "\n".join(part.strip() for part in text_parts if str(part).strip())
        if not text:
            raise PaddleOutputSchemaError(
                "PaddleOCR returned no readable text for the supplied page."
            )

        return {
            "text": text,
            "page_number": source_page_number,
            "correlation_id": correlation_id,
            "image_width": image_width,
            "image_height": image_height,
            "engine": "paddleocr_vl",
            "result": result,
        }
