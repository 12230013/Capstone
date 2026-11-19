"""MongoDB persistence for local OCR documents and their results."""

import hashlib
from io import BytesIO
from typing import Any

from app.database.connection import db, ocr_documents_collection

_GRIDFS_BUCKET_NAME = "ocr_document_files"


class OCRDocumentConflictError(RuntimeError):
    """Raised when an existing OCR document cannot safely be reused."""


def _require_owner_user_id(owner_user_id: Any) -> str:
    if not isinstance(owner_user_id, str) or not owner_user_id.strip():
        raise ValueError("An OCR owner user ID is required.")
    return owner_user_id.strip()


def _require_storage() -> tuple[Any, Any]:
    if db is None or ocr_documents_collection is None:
        raise RuntimeError("OCR MongoDB storage is not available.")
    return db, ocr_documents_collection


def _file_record(database: Any, document_id: str) -> dict | None:
    return database[f"{_GRIDFS_BUCKET_NAME}.files"].find_one({"_id": document_id})


def _ensure_gridfs_document(
    database: Any,
    document_id: str,
    content_sha256: str,
    filename: str,
    mime_type: str,
    content: bytes,
) -> None:
    file_record = _file_record(database, document_id)
    if file_record is not None:
        metadata = file_record.get("metadata") or {}
        if metadata.get("content_sha256") != content_sha256:
            raise OCRDocumentConflictError(
                "An existing GridFS file does not match the document content."
            )
        return

    from gridfs import GridFSBucket
    from gridfs.errors import FileExists

    bucket = GridFSBucket(database, bucket_name=_GRIDFS_BUCKET_NAME)
    try:
        bucket.upload_from_stream_with_id(
            document_id,
            filename,
            BytesIO(content),
            metadata={
                "document_id": document_id,
                "mime_type": mime_type,
                "content_sha256": content_sha256,
            },
        )
    except FileExists:
        existing_file_record = _file_record(database, document_id)
        if existing_file_record is None:
            raise
        existing_metadata = existing_file_record.get("metadata") or {}
        if existing_metadata.get("content_sha256") != content_sha256:
            raise OCRDocumentConflictError(
                "An existing GridFS file does not match the document content."
            ) from None


def persist_ocr_document(
    status: dict[str, Any],
    content: bytes,
    *,
    allow_retry: bool = False,
) -> None:
    """Store the source file in GridFS and its owner/status metadata in MongoDB."""
    database, collection = _require_storage()
    document_id = status["document_id"]
    content_sha256 = status.get("content_sha256") or document_id
    if hashlib.sha256(content).hexdigest() != content_sha256:
        raise ValueError("The OCR document content hash does not match its content.")
    record = {
        **status,
        "_id": document_id,
        "content_sha256": content_sha256,
        "source_file_id": document_id,
        "source_storage": "gridfs",
    }
    owner_user_id = _require_owner_user_id(status.get("owner_user_id"))

    existing = collection.find_one({"_id": document_id})
    if existing is not None:
        if (
            not allow_retry
            or existing.get("content_sha256") != content_sha256
            or existing.get("owner_user_id") != status.get("owner_user_id")
        ):
            raise OCRDocumentConflictError(
                "An OCR document with this identifier already exists."
            )
        _ensure_gridfs_document(
            database,
            document_id,
            content_sha256,
            status["filename"],
            status["mime_type"],
            content,
        )
        updates = {key: value for key, value in record.items() if key != "_id"}
        result = collection.update_one(
            {"_id": document_id, "owner_user_id": owner_user_id},
            {"$set": updates},
        )
        if result.matched_count != 1:
            raise RuntimeError("The OCR MongoDB document owner could not be verified.")
        return

    _ensure_gridfs_document(
        database,
        document_id,
        content_sha256,
        status["filename"],
        status["mime_type"],
        content,
    )
    record["ocr_result"] = None
    collection.insert_one(record)


def update_ocr_document(
    document_id: str,
    updates: dict[str, Any],
    *,
    owner_user_id: str,
    ocr_result: dict[str, Any] | None = None,
) -> None:
    """Persist OCR status changes and the full page-level result."""
    _, collection = _require_storage()
    owner_user_id = _require_owner_user_id(owner_user_id)
    fields = dict(updates)
    if ocr_result is not None:
        fields["ocr_result"] = ocr_result
    result = collection.update_one(
        {"_id": document_id, "owner_user_id": owner_user_id},
        {"$set": fields},
    )
    if result.matched_count != 1:
        raise RuntimeError("The OCR MongoDB document record is missing.")
