from pathlib import Path
from pypdf import PdfReader
from docx import Document


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".txt"
}


def load_document(file_path: str):
    """
    Load a supported document and return its text and metadata.
    """

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(
            f"Document not found: {file_path}"
        )

    extension = path.suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported document type: {extension}"
        )

    # =====================================================
    # PDF
    # =====================================================

    if extension == ".pdf":
        return load_pdf(path)

    # =====================================================
    # DOCX
    # =====================================================

    if extension == ".docx":
        return load_docx(path)

    # =====================================================
    # TXT
    # =====================================================

    if extension == ".txt":
        return load_txt(path)


def load_pdf(path: Path):
    reader = PdfReader(str(path))

    pages = []

    for page_number, page in enumerate(reader.pages, start=1):

        text = page.extract_text() or ""

        pages.append({
            "page_number": page_number,
            "text": text.strip()
        })

    full_text = "\n\n".join(
        page["text"]
        for page in pages
        if page["text"]
    )

    return {
        "filename": path.name,
        "file_type": "pdf",
        "text": full_text,
        "pages": pages,
        "page_count": len(reader.pages)
    }


def load_docx(path: Path):
    document = Document(str(path))

    paragraphs = []

    for paragraph in document.paragraphs:

        text = paragraph.text.strip()

        if text:
            paragraphs.append(text)

    full_text = "\n\n".join(paragraphs)

    return {
        "filename": path.name,
        "file_type": "docx",
        "text": full_text,
        "paragraph_count": len(paragraphs)
    }


def load_txt(path: Path):
    text = path.read_text(
        encoding="utf-8"
    ).strip()

    return {
        "filename": path.name,
        "file_type": "txt",
        "text": text
    }