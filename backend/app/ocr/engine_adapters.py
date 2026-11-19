"""Shared page-level interface for OCR engine adapters."""

from typing import Any, Protocol

from PIL import Image


class OCRPageAdapter(Protocol):
    """Engine adapter contract used by document OCR routing."""

    name: str

    def initialize(self) -> None:
        """Verify or initialize the selected engine before page processing."""

    def process_page(
        self,
        image: Image.Image,
        page_number: int,
        correlation_id: str,
    ) -> tuple[str, float | None, list[float], dict[str, Any]]:
        """Recognize one page and return text, confidence and preprocessing data."""
