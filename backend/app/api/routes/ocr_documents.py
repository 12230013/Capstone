"""Authenticated OCR upload, review, and indexing endpoints."""

import hashlib
import ipaddress
import json
import logging
import os
import re
import tempfile
import threading
import warnings
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
)
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from app.database.ocr_storage import (
    OCRDocumentConflictError,
    persist_ocr_document,
    update_ocr_document,
)
from app.ocr.layout import LAYOUT_VERSION
from app.ocr import config
from app.ocr.document_ocr import run_document_ocr, save_ocr_result
from app.utils.sessions import require_session


router = APIRouter(
    prefix="/api/ocr/documents",
    tags=["OCR documents"],
)

logger = logging.getLogger(__name__)
_DOCUMENT_ID_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_MIME_TO_EXTENSION = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}
_IMAGE_FORMATS = {
    "image/png": "PNG",
    "image/jpeg": "JPEG",
}
_STATUS_LOCK = threading.RLock()
_OCR_PROCESS_LOCK = threading.Lock()
_INDEX_LOCK = threading.Lock()


class FormField(BaseModel):
    label: str = Field(strict=True, max_length=10000)
    value: str = Field(strict=True, max_length=100000)


class ReviewBlock(BaseModel):
    type: str = Field(pattern="^(text|table|form)$")
    text: str = Field(default="", max_length=1000000)
    rows: list[list[str]] = Field(default_factory=list, max_length=1000)
    fields: list[FormField] = Field(default_factory=list, max_length=1000)
    cell_spans: list[list[dict[str, int]]] | None = None
    column_widths: list[float] | None = None
    has_header: bool | None = None


class ReviewedOCRPage(BaseModel):
    page_number: int = Field(strict=True, ge=1)
    text: str = Field(strict=True)
    blocks: list[ReviewBlock] | None = Field(default=None, max_length=1000)
    editor_json: dict[str, Any] | None = None


class IndexConfirmation(BaseModel):
    review_confirmed: bool = Field(strict=True)
    case_no: str | None = Field(default=None, min_length=1, max_length=64)
    case_number: str | None = Field(default=None, max_length=64)
    reviewed_pages: list[ReviewedOCRPage] | None = None


def _apply_reviewed_page_text(
    result: dict[str, Any],
    reviewed_pages: list[ReviewedOCRPage],
) -> None:
    pages = result.get("pages")
    if not isinstance(pages, list) or not pages:
        raise HTTPException(
            status_code=409,
            detail="The OCR result has no editable page data.",
        )

    original_page_numbers = [
        page.get("page_number") if isinstance(page, dict) else None
        for page in pages
    ]
    reviewed_page_numbers = [page.page_number for page in reviewed_pages]
    if (
        any(
            not isinstance(page_number, int)
            or isinstance(page_number, bool)
            or page_number < 1
            for page_number in original_page_numbers
        )
        or len(set(original_page_numbers)) != len(original_page_numbers)
        or len(set(reviewed_page_numbers)) != len(reviewed_page_numbers)
        or set(reviewed_page_numbers) != set(original_page_numbers)
    ):
        raise HTTPException(
            status_code=400,
            detail="Reviewed pages must match the OCR result page numbers exactly.",
        )

    from app.ocr.layout import blocks_text
    from app.ocr.editor_document import editor_blocks
    for reviewed in reviewed_pages:
        if reviewed.editor_json is not None:
            try:
                reviewed.blocks = [ReviewBlock(**b) for b in editor_blocks(reviewed.editor_json)]
            except (ValueError, TypeError, KeyError) as exc:
                raise HTTPException(400, str(exc)) from exc
        if reviewed.blocks is not None:
            for block in reviewed.blocks:
                if block.type == "table" and (not block.rows or not block.rows[0] or len(block.rows[0]) > 100 or any(len(r) != len(block.rows[0]) for r in block.rows)):
                    raise HTTPException(400, "Tables must have equally sized, non-empty rows (up to 100 columns).")

    reviewed_text_by_page = {
        page.page_number: page.text for page in reviewed_pages
    }
    for page in pages:
        page.setdefault("extracted_text", page["text"])
        reviewed = next(p for p in reviewed_pages if p.page_number == page["page_number"])
        if reviewed.editor_json is not None:
            page["editor_json"] = reviewed.editor_json
        else:
            page.pop("editor_json", None)
        if reviewed.blocks is not None:
            page.setdefault("raw_text", page["text"])
            page["blocks"] = [b.model_dump() for b in reviewed.blocks]
            page["text"] = blocks_text(page["blocks"])
        else:
            page["text"] = reviewed_text_by_page[page["page_number"]]
            page["blocks"] = [{"type": "text", "text": page["text"]}]

    result["reviewed_at"] = datetime.now(timezone.utc).isoformat()

def require_local_development(request: Request) -> None:
    client = request.client
    if (
        config.APP_ENV not in {"development", "dev", "local"}
        or client is None
        or not _is_loopback_host(client.host)
    ):
        raise HTTPException(status_code=404, detail="Not found.")


def require_ocr_access(request: Request) -> None:
    """Allow loopback development or explicitly enabled authenticated deployment."""
    if config.OCR_DEPLOYMENT_ENABLED:
        return
    require_local_development(request)


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_loopback


def _session_owner_id(session: dict[str, Any]) -> str:
    owner_user_id = session.get("user_id")
    if not isinstance(owner_user_id, str) or not owner_user_id.strip():
        raise HTTPException(status_code=401, detail="Authentication is required.")
    return owner_user_id.strip()


def _document_id(value: str) -> str:
    if not _DOCUMENT_ID_PATTERN.fullmatch(value):
        raise HTTPException(status_code=404, detail="Document not found.")
    return value


def _authorize_document(
    status: dict[str, Any],
    owner_user_id: str,
) -> None:
    if status.get("owner_user_id") == owner_user_id:
        return
    raise HTTPException(status_code=404, detail="Document not found.")


def _status_path(document_id: str) -> Path:
    return config.OCR_RESULTS_DIR / f"{document_id}.status.json"


def _write_json_atomically(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{path.stem}-",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(value, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _read_status(document_id: str) -> dict[str, Any] | None:
    path = _status_path(document_id)
    try:
        with path.open(encoding="utf-8") as status_file:
            status = json.load(status_file)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception("Could not read OCR status for %s", document_id)
        raise HTTPException(
            status_code=503,
            detail="Document status is temporarily unavailable.",
        ) from exc
    if not isinstance(status, dict) or status.get("document_id") != document_id:
        logger.error("Invalid OCR status record for %s", document_id)
        raise HTTPException(
            status_code=503,
            detail="Document status is temporarily unavailable.",
        )
    return status


def _update_status(
    document_id: str,
    owner_user_id: str,
    **updates: Any,
) -> dict[str, Any]:
    with _STATUS_LOCK:
        status = _read_status(document_id)
        if status is None:
            raise FileNotFoundError("OCR status record is missing.")
        if status.get("owner_user_id") != owner_user_id:
            raise RuntimeError("The OCR document owner could not be verified.")
        status.update(updates)
        status["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_json_atomically(_status_path(document_id), status)
        persisted_updates = dict(updates)
        persisted_updates["updated_at"] = status["updated_at"]
        update_ocr_document(
            document_id,
            persisted_updates,
            owner_user_id=owner_user_id,
        )
        return status


async def _read_upload(upload: UploadFile) -> bytes:
    raw_filename = upload.filename
    if not isinstance(raw_filename, str) or not raw_filename.strip():
        raise HTTPException(status_code=400, detail="A filename is required.")
    filename = raw_filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not filename or len(filename) > 255 or any(
        ord(character) < 32 for character in filename
    ):
        raise HTTPException(status_code=400, detail="Invalid filename.")

    extension = Path(filename).suffix.lower()
    expected_mime = next(
        (
            mime_type
            for mime_type, suffix in _MIME_TO_EXTENSION.items()
            if suffix == extension
            or (mime_type == "image/jpeg" and extension == ".jpeg")
        ),
        None,
    )
    if expected_mime is None:
        raise HTTPException(
            status_code=415,
            detail="Only PDF, PNG, JPG, and JPEG files are supported.",
        )
    if upload.content_type != expected_mime:
        raise HTTPException(
            status_code=415,
            detail="The file extension and MIME type do not match.",
        )

    maximum_bytes = config.OCR_MAX_UPLOAD_BYTES
    chunks = []
    total_bytes = 0
    while True:
        chunk_size = min(64 * 1024, maximum_bytes + 1 - total_bytes)
        if chunk_size <= 0:
            raise HTTPException(
                status_code=413,
                detail="The uploaded file is too large.",
            )
        content = await upload.read(chunk_size)
        if not content:
            break
        total_bytes += len(content)
        if total_bytes > maximum_bytes:
            raise HTTPException(
                status_code=413,
                detail="The uploaded file is too large.",
            )
        chunks.append(content)
    if total_bytes == 0:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    data = b"".join(chunks)
    _validate_content(data, expected_mime)
    return data


def _validate_content(data: bytes, mime_type: str) -> None:
    if mime_type == "application/pdf":
        if b"%PDF-" not in data[:1024]:
            raise HTTPException(
                status_code=415,
                detail="The uploaded content is not a PDF.",
            )
        try:
            with fitz.open(stream=data, filetype="pdf") as document:
                if document.is_encrypted or document.page_count < 1:
                    raise HTTPException(
                        status_code=400,
                        detail="The PDF is encrypted or contains no pages.",
                    )
        except HTTPException:
            raise
        except (
            fitz.FileDataError,
            fitz.EmptyFileError,
            ValueError,
            RuntimeError,
        ) as exc:
            raise HTTPException(
                status_code=400,
                detail="The PDF is invalid or unreadable.",
            ) from exc
        return

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format != _IMAGE_FORMATS[mime_type]:
                    raise HTTPException(
                        status_code=415,
                        detail="The uploaded image content does not match its MIME type.",
                    )
                image.verify()
    except HTTPException:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=400,
            detail="The image is invalid or unreadable.",
        ) from exc


def _store_upload(
    document_id: str,
    extension: str,
    data: bytes,
    content_sha256: str,
) -> Path:
    destination = config.DOCUMENTS_DIR / f"{document_id}{extension}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        existing_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
        if existing_hash != content_sha256:
            raise FileExistsError("An existing OCR source file has different content.")
        return destination
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{document_id}-",
            suffix=".upload",
            dir=destination.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(data)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return destination


def _owner_scoped_document_id(owner_user_id: str, content_sha256: str) -> str:
    identity = f"acc-ocr-document\0{owner_user_id}\0{content_sha256}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _process_document(document_id: str, owner_user_id: str) -> None:
    status = _read_status(document_id)
    if status is None:
        logger.error("OCR task has no status record for %s", document_id)
        return
    if status.get("owner_user_id") != owner_user_id:
        logger.error("OCR task owner mismatch for %s", document_id)
        return
    _update_status(
        document_id,
        owner_user_id,
        status="processing",
        error_code=None,
    )
    source_path = config.DOCUMENTS_DIR / (
        f"{document_id}{_MIME_TO_EXTENSION[status['mime_type']]}"
    )
    try:
        with _OCR_PROCESS_LOCK:
            result = run_document_ocr(
                str(source_path),
                document_id,
                status["filename"],
                status["mime_type"],
                correlation_id=document_id,
            )
        if not isinstance(result, dict) or result.get("document_id") != document_id:
            raise ValueError("OCR returned a result for a different document.")
        ocr_status = result.get("ocr_status")
        if ocr_status not in {"completed", "not_required", "manual_review"}:
            raise RuntimeError("OCR did not produce a usable result.")
        if "case_number" in status:
            result["case_number"] = status["case_number"]
        save_ocr_result(result)
        update_ocr_document(
            document_id,
            {},
            owner_user_id=owner_user_id,
            ocr_result=result,
        )
        _update_status(
            document_id,
            owner_user_id,
            status=ocr_status,
            ocr_status=ocr_status,
            extraction_method=result.get("extraction_method"),
            page_count=result.get("page_count", 0),
            layout_version=result.get("layout_version"),
            index_status="not_indexed",
            error_code=None,
        )
    except Exception:
        logger.exception("OCR processing failed for %s", document_id)
        _update_status(
            document_id,
            owner_user_id,
            status="failed",
            ocr_status="failed",
            error_code="processing_failed",
        )


def _read_ocr_result(document_id: str) -> dict[str, Any] | None:
    result_path = config.OCR_RESULTS_DIR / f"{document_id}.json"
    try:
        with result_path.open(encoding="utf-8") as result_file:
            result = json.load(result_file)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception("Could not read OCR result for %s", document_id)
        raise HTTPException(
            status_code=503,
            detail="Document result is temporarily unavailable.",
        ) from exc
    if not isinstance(result, dict) or result.get("document_id") != document_id:
        logger.error("Invalid OCR result record for %s", document_id)
        raise HTTPException(
            status_code=503,
            detail="Document result is temporarily unavailable.",
        )
    return result


@router.post(
    "",
    status_code=202,
    dependencies=[Depends(require_ocr_access)],
)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session: dict[str, Any] = Depends(require_session),
) -> Any:
    owner_user_id = _session_owner_id(session)
    try:
        data = await _read_upload(file)
        if file.filename is None or file.content_type is None:
            raise HTTPException(status_code=400, detail="Upload metadata is missing.")
        filename = file.filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
        mime_type = file.content_type
    finally:
        await file.close()

    content_sha256 = hashlib.sha256(data).hexdigest()
    document_id = content_sha256
    extension = _MIME_TO_EXTENSION[mime_type]
    with _STATUS_LOCK:
        existing_status = _read_status(document_id)
        if (
            existing_status is not None
            and existing_status.get("owner_user_id") != owner_user_id
        ):
            document_id = _owner_scoped_document_id(
                owner_user_id,
                content_sha256,
            )
            existing_status = _read_status(document_id)

        refresh_existing = False
        if existing_status and existing_status.get("status") in {"completed", "not_required"} and existing_status.get("index_status") not in {"indexed", "indexing"}:
            previous = _read_ocr_result(document_id)
            reviewed = previous and (previous.get("reviewed_at") or any(p.get("editor_json") for p in previous.get("pages", [])))
            refresh_existing = not reviewed and (previous is None or previous.get("layout_version") != LAYOUT_VERSION or previous.get("ocr_engine") != config.OCR_ENGINE or previous.get("ocr_model") != config.OCR_MODEL_ID)

        if existing_status and existing_status.get("status") != "failed" and not refresh_existing:
            _authorize_document(existing_status, owner_user_id)
            try:
                persist_ocr_document(existing_status, data, allow_retry=True)
                existing_result = _read_ocr_result(document_id)
                if existing_result is not None:
                    update_ocr_document(
                        document_id,
                        {},
                        owner_user_id=owner_user_id,
                        ocr_result=existing_result,
                    )
            except OCRDocumentConflictError as exc:
                raise HTTPException(
                    status_code=409,
                    detail="The existing OCR document could not be reconciled.",
                ) from exc
            except Exception as exc:
                logger.exception(
                    "Could not reconcile existing OCR document %s",
                    document_id,
                )
                raise HTTPException(
                    status_code=503,
                    detail="OCR document storage is temporarily unavailable.",
                ) from exc
            return JSONResponse(
                status_code=200,
                content={**existing_status, "duplicate": True},
            )
        now = datetime.now(timezone.utc).isoformat()
        status = {
            "document_id": document_id,
            "content_sha256": content_sha256,
            "owner_user_id": owner_user_id,
            "filename": filename,
            "mime_type": mime_type,
            "status": "queued",
            "ocr_status": None,
            "index_status": "not_indexed",
            "created_at": (
                existing_status.get("created_at", now)
                if existing_status
                else now
            ),
            "updated_at": now,
            "case_number": existing_status.get("case_number") if existing_status else None,
            "error_code": None,
        }
        try:
            persist_ocr_document(status, data, allow_retry=True)
        except OCRDocumentConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail="A document with this identifier already exists.",
            ) from exc
        except Exception as exc:
            logger.exception("Could not persist uploaded OCR document %s", document_id)
            raise HTTPException(
                status_code=503,
                detail="OCR document storage is temporarily unavailable.",
            ) from exc
        _store_upload(document_id, extension, data, content_sha256)
        _write_json_atomically(_status_path(document_id), status)

    background_tasks.add_task(_process_document, document_id, owner_user_id)
    return status


@router.post("/{document_id}/reprocess", dependencies=[Depends(require_ocr_access)])
def reprocess_document(document_id: str, background_tasks: BackgroundTasks, session: dict[str, Any] = Depends(require_session)):
    """Explicitly re-extract a retained original with the current layout detector."""
    owner = _session_owner_id(session)
    document_id = _document_id(document_id)
    with _INDEX_LOCK, _STATUS_LOCK:
        status = _read_status(document_id)
        if status is None:
            raise HTTPException(404, "Document not found.")
        _authorize_document(status, owner)
        if status.get("status") in {"queued", "processing"} or status.get("index_status") == "indexing":
            raise HTTPException(409, "This document is already being processed.")
        source = config.DOCUMENTS_DIR / f"{document_id}{_MIME_TO_EXTENSION[status['mime_type']]}"
        if not source.is_file():
            raise HTTPException(409, "The local original is unavailable. Upload the original again before re-extracting.")
        status = _update_status(document_id, owner, status="queued", ocr_status=None, index_status="not_indexed", error_code=None)
    background_tasks.add_task(_process_document, document_id, owner)
    return JSONResponse(status_code=202, content=status)


@router.get(
    "/{document_id}/status",
    dependencies=[Depends(require_ocr_access)],
)
def get_document_status(
    document_id: str,
    session: dict[str, Any] = Depends(require_session),
) -> dict[str, Any]:
    owner_user_id = _session_owner_id(session)
    document_id = _document_id(document_id)
    status = _read_status(document_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    _authorize_document(status, owner_user_id)
    return status


@router.get(
    "/{document_id}",
    dependencies=[Depends(require_ocr_access)],
)
def get_document_result(
    document_id: str,
    session: dict[str, Any] = Depends(require_session),
) -> dict[str, Any]:
    owner_user_id = _session_owner_id(session)
    document_id = _document_id(document_id)
    status = _read_status(document_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    _authorize_document(status, owner_user_id)
    if status.get("status") == "failed":
        return {
            "document_id": document_id,
            "status": "failed",
            "error_code": status.get("error_code"),
        }
    result = _read_ocr_result(document_id)
    if result is None:
        raise HTTPException(status_code=202, detail=status)
    return {
        **result,
        "active_ocr_model": config.OCR_MODEL_ID,
        "active_ocr_engine": config.OCR_ENGINE,
        "model_upgrade_available": result.get("extraction_method") != "direct" and (
            result.get("ocr_model") != config.OCR_MODEL_ID or result.get("ocr_engine") != config.OCR_ENGINE
        ),
    }



class OCRTextEvaluation(BaseModel):
    page_number: int = Field(strict=True, ge=1)
    reference_text: str = Field(strict=True, min_length=1, max_length=20_000)


@router.post("/{document_id}/evaluate", dependencies=[Depends(require_local_development)])
def evaluate_document_text(
    document_id: str,
    evaluation: OCRTextEvaluation,
    session: dict[str, Any] = Depends(require_session),
) -> dict[str, Any]:
    # Reuse the same session ownership checks as result downloads.
    result = get_document_result(document_id, session)
    page = next((p for p in result.get("pages", []) if p.get("page_number") == evaluation.page_number), None)
    if page is None:
        raise HTTPException(404, "Extracted page not found.")
    prediction = page.get("extracted_text")
    if prediction is None:
        if result.get("reviewed_at") or page.get("editor_json"):
            raise HTTPException(409, "The original evaluation text is unavailable for this older review. Re-extract the original first.")
        prediction = page.get("text", "")
    from app.ocr.evaluation import evaluate_text
    try:
        metrics = evaluate_text(prediction, evaluation.reference_text)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"page_number": evaluation.page_number, **metrics}


def _create_qdrant_adapter() -> Any:
    from app.ocr.qdrant_adapter import OCRQdrantAdapter

    return OCRQdrantAdapter()


@router.post(
    "/{document_id}/index",
    dependencies=[Depends(require_ocr_access)],
)
def index_document(
    document_id: str,
    confirmation: IndexConfirmation,
    session: dict[str, Any] = Depends(require_session),
) -> dict[str, Any]:
    owner_user_id = _session_owner_id(session)
    document_id = _document_id(document_id)
    if not confirmation.review_confirmed:
        raise HTTPException(
            status_code=400,
            detail="Review confirmation is required before indexing.",
        )
    with _INDEX_LOCK:
        status = _read_status(document_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        if status.get("owner_user_id") != owner_user_id:
            raise HTTPException(status_code=404, detail="Document not found.")
        case_no = (
            confirmation.case_no.strip().upper()
            if confirmation.case_no and confirmation.case_no.strip()
            else None
        )
        if case_no is not None:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Case-linked OCR indexing is unavailable until case "
                    "authorization is configured."
                ),
            )
        if status.get("status") not in {"completed", "not_required"}:
            raise HTTPException(
                status_code=409,
                detail="A completed OCR result is required before indexing.",
            )
        if status.get("index_status") == "indexed" and confirmation.reviewed_pages is None and "case_number" not in confirmation.model_fields_set:
            return status

        result = _read_ocr_result(document_id)
        if result is None or result.get("ocr_status") not in {
            "completed",
            "not_required",
        }:
            raise HTTPException(
                status_code=409,
                detail="A completed OCR result is required before indexing.",
            )
        if confirmation.reviewed_pages is not None:
            try:
                _apply_reviewed_page_text(result, confirmation.reviewed_pages)
            except HTTPException as exc:
                logger.warning(
                    "OCR review rejected for %s: %s (original pages=%s, submitted pages=%s)",
                    document_id, exc.detail,
                    [p.get("page_number") for p in result.get("pages", [])],
                    [p.page_number for p in confirmation.reviewed_pages],
                )
                raise
        if not any(
            isinstance(page, dict)
            and isinstance(page.get("text"), str)
            and page["text"].strip()
            for page in result.get("pages", [])
        ):
            raise HTTPException(
                status_code=409,
                detail="The OCR result contains no indexable text.",
            )

        if "case_number" in confirmation.model_fields_set:
            result["case_number"] = (confirmation.case_number or "").strip() or None

        if confirmation.reviewed_pages is not None or "case_number" in confirmation.model_fields_set:
            save_ocr_result(result)
            update_ocr_document(
                document_id,
                {},
                owner_user_id=owner_user_id,
                ocr_result=result,
            )

        logger.info(
            "Local OCR document indexing requested after review",
            extra={"document_id": document_id, "action": "ocr_document_index"},
        )
        _update_status(
            document_id,
            owner_user_id,
            index_status="indexing",
            index_error_code=None,
            case_no=case_no,
            case_number=result.get("case_number"),
        )
        try:
            indexing_result = _create_qdrant_adapter().upsert_document(
                result,
                case_no=case_no,
                owner_user_id=owner_user_id,
            )
        except Exception:
            logger.exception("OCR document indexing failed for %s", document_id)
            _update_status(
                document_id,
                owner_user_id,
                index_status="index_failed",
                index_error_code="indexing_failed",
            )
            raise HTTPException(
                status_code=503,
                detail="The OCR result could not be indexed.",
            ) from None

        return _update_status(
            document_id,
            owner_user_id,
            index_status="indexed",
            index_error_code=None,
            chunks_indexed=indexing_result.get("chunks_upserted", 0),
            collection=indexing_result.get("collection"),
        )
