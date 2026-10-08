"""Direct, page-preserving text extraction for digital PDFs only."""

import fitz

from app.ocr.document_detection import (
    InvalidPDFError,
    classify_page_texts,
    normalize_extracted_page_text,
    open_pdf_document,
)


def extract_digital_pdf(pdf_path: str, document_id: str) -> dict:
    """Extract normalized page text, refusing scanned PDFs instead of running OCR."""
    document = open_pdf_document(pdf_path)
    try:
        try:
            raw_page_texts = [
                page.get_text("text", sort=True)
                for page in document
            ]
        except (fitz.FileDataError, ValueError, RuntimeError) as exc:
            raise InvalidPDFError("The PDF could not be read") from exc

        detection = classify_page_texts(raw_page_texts)
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
                "pages": [],
            }

        pages = [
            {
                "page_number": page_number,
                "text": normalize_extracted_page_text(text),
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
        "page_count": detection["page_count"],
        "pages_with_text": detection["pages_with_text"],
        "total_text_characters": sum(
            len("".join(page["text"].split()))
            for page in pages
        ),
        "pages": pages,
    }
