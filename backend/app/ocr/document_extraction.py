"""Direct, page-preserving text extraction for digital PDFs only."""

import fitz

from app.ocr.document_detection import (
    InvalidPDFError,
    classify_page_texts,
    normalize_extracted_page_text,
    open_pdf_document,
    page_image_coverage,
    page_text_area_coverage,
)


def extract_digital_pdf(pdf_path: str, document_id: str) -> dict:
    """Extract normalized page text, refusing scanned PDFs instead of running OCR."""
    document = open_pdf_document(pdf_path)
    try:
        try:
            raw_page_texts = [page.get_text("text", sort=True) for page in document]
            image_coverages = [page_image_coverage(page) for page in document]
            text_coverages = [page_text_area_coverage(page) for page in document]
        except (fitz.FileDataError, ValueError, RuntimeError) as exc:
            raise InvalidPDFError("The PDF could not be read") from exc

        detection = classify_page_texts(
            raw_page_texts,
            image_coverages=image_coverages,
            text_coverages=text_coverages,
        )
        if detection["ocr_required"]:
            return {
                "document_id": document_id,
                "document_type": "pdf",
                "document_classification": detection["classification"],
                "extraction_method": "ocr_required",
                "ocr_required": True,
                "page_count": detection["page_count"],
                "pages_with_text": detection["pages_with_text"],
                "total_text_characters": detection["total_text_characters"],
                "quality_decision": detection["quality_decision"],
                "page_decisions": detection["page_decisions"],
                "pages": [],
            }

        pages = [
            {
                "page_number": page_number,
                "text": normalize_extracted_page_text(text),
                "extraction_method": "direct",
                "quality_decision": detection["page_decisions"][page_number - 1]["decision"],
            }
            for page_number, text in enumerate(raw_page_texts, start=1)
        ]
    finally:
        document.close()

    return {
        "document_id": document_id,
        "document_type": "pdf",
        "document_classification": detection["classification"],
        "extraction_method": "direct",
        "ocr_required": False,
        "quality_decision": detection["quality_decision"],
        "page_decisions": detection["page_decisions"],
        "page_count": detection["page_count"],
        "pages_with_text": detection["pages_with_text"],
        "total_text_characters": sum(
            len("".join(page["text"].split()))
            for page in pages
        ),
        "pages": pages,
    }
