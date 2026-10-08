import ntpath
import os
import shutil
import tempfile
from datetime import timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ocr.config import DOCUMENTS_DIR
from app.ocr.database import UploadedDocument, get_db
from app.ocr.document_detection import InvalidPDFError, detect_pdf_text
from app.ocr.document_extraction import extract_digital_pdf
from app.ocr.document_ocr import (
    InvalidOCRDocumentError,
    OCRProcessingError,
    TesseractUnavailableError,
    failed_ocr_result,
    run_document_ocr,
    save_ocr_result,
)


router = APIRouter(prefix="/documents", tags=["Document OCR"])

ALLOWED_TYPES = {
    ".pdf": ("application/pdf", b"%PDF-"),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
}
READ_SIZE = 1024 * 1024


def _metadata(document: UploadedDocument) -> dict:
    upload_time = document.upload_time
    if upload_time.tzinfo is None:
        upload_time = upload_time.replace(tzinfo=timezone.utc)
    return {
        "document_id": document.document_id,
        "filename": document.filename,
        "file_type": document.file_type,
        "uploaded_by": document.uploaded_by,
        "upload_time": upload_time.isoformat(),
        "status": document.status,
    }


def _get_document(document_id: str, db: Session) -> UploadedDocument:
    document = (
        db.query(UploadedDocument)
        .filter(UploadedDocument.document_id == document_id)
        .first()
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


def _document_path(document: UploadedDocument) -> str:
    path = os.path.join(DOCUMENTS_DIR, document.filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Stored document file not found")
    return path


@router.post("/upload", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    uploaded_by: str = Form(..., min_length=1, max_length=100),
    db: Session = Depends(get_db),
):
    filename = file.filename
    if (
        not filename
        or len(filename) > 255
        or filename != ntpath.basename(filename)
        or "\x00" in filename
    ):
        raise HTTPException(
            status_code=400,
            detail="A plain filename of at most 255 characters is required",
        )

    file_type_and_signature = ALLOWED_TYPES.get(os.path.splitext(filename)[1].lower())
    if file_type_and_signature is None:
        raise HTTPException(
            status_code=415,
            detail="Only PDF, PNG, JPG, and JPEG files are accepted",
        )
    uploaded_by = uploaded_by.strip()
    if not uploaded_by:
        raise HTTPException(status_code=422, detail="uploaded_by cannot be blank")

    mime_type, signature = file_type_and_signature
    header = await file.read(1024)
    signature_matches = (
        signature in header if filename.lower().endswith(".pdf") else header.startswith(signature)
    )
    if not signature_matches:
        raise HTTPException(status_code=400, detail="File content does not match its extension")

    os.makedirs(DOCUMENTS_DIR, exist_ok=True)
    temporary_path = None
    destination_path = os.path.join(DOCUMENTS_DIR, filename)
    destination_created = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".upload-", dir=DOCUMENTS_DIR, delete=False
        ) as temporary_file:
            temporary_path = temporary_file.name
            temporary_file.write(header)
            while chunk := await file.read(READ_SIZE):
                temporary_file.write(chunk)

        try:
            with open(destination_path, "xb") as destination:
                destination_created = True
                with open(temporary_path, "rb") as source:
                    shutil.copyfileobj(source, destination)
        except FileExistsError as exc:
            raise HTTPException(
                status_code=409,
                detail="A document with this filename has already been uploaded",
            ) from exc

        document = UploadedDocument(
            filename=filename,
            file_type=mime_type,
            uploaded_by=uploaded_by,
        )
        db.add(document)
        db.flush()
        document.document_id = f"DOC-{document.id:05d}"
        db.commit()
        db.refresh(document)
        return _metadata(document)
    except IntegrityError as exc:
        db.rollback()
        if destination_created and os.path.exists(destination_path):
            os.remove(destination_path)
        raise HTTPException(
            status_code=409,
            detail="A document with this filename has already been uploaded",
        ) from exc
    except Exception:
        db.rollback()
        if destination_created and os.path.exists(destination_path):
            os.remove(destination_path)
        raise
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.remove(temporary_path)


@router.get("/{document_id}")
def get_document(document_id: str, db: Session = Depends(get_db)):
    return _metadata(_get_document(document_id, db))


@router.post("/{document_id}/detect")
def detect_document_text(document_id: str, db: Session = Depends(get_db)):
    document = _get_document(document_id, db)
    if document.file_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Text detection supports PDF files only")
    try:
        result = detect_pdf_text(_document_path(document))
    except InvalidPDFError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"document_id": document.document_id, "document_type": "pdf", **result}


@router.post("/{document_id}/extract")
def extract_document_text(document_id: str, db: Session = Depends(get_db)):
    document = _get_document(document_id, db)
    if document.file_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Text extraction supports PDF files only")
    try:
        return extract_digital_pdf(_document_path(document), document.document_id)
    except InvalidPDFError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _ocr_error_response(result: dict, status_code: int) -> JSONResponse:
    try:
        save_ocr_result(result)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Could not save the OCR result.") from exc
    return JSONResponse(status_code=status_code, content=result)


@router.post("/{document_id}/ocr")
def ocr_document(document_id: str, db: Session = Depends(get_db)):
    document = _get_document(document_id, db)
    if document.file_type not in {"application/pdf", "image/png", "image/jpeg"}:
        raise HTTPException(
            status_code=415,
            detail="OCR supports PDF, PNG, JPG, and JPEG files only",
        )

    file_path = _document_path(document)
    try:
        result = run_document_ocr(
            file_path,
            document.document_id,
            document.filename,
            document.file_type,
        )
    except TesseractUnavailableError as exc:
        result = failed_ocr_result(
            document.document_id, document.filename, document.file_type, str(exc)
        )
        return _ocr_error_response(result, 503)
    except InvalidOCRDocumentError as exc:
        result = failed_ocr_result(
            document.document_id, document.filename, document.file_type, str(exc)
        )
        return _ocr_error_response(result, 422)
    except OCRProcessingError as exc:
        result = failed_ocr_result(
            document.document_id, document.filename, document.file_type, str(exc)
        )
        return _ocr_error_response(result, 500)

    if result["ocr_status"] == "not_required":
        return result
    try:
        save_ocr_result(result)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Could not save the OCR result.") from exc
    if result["ocr_status"] == "failed":
        return JSONResponse(status_code=422, content=result)
    return result
