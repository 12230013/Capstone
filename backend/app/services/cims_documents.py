"""Reconcile a mounted CIMS drop and retrieve published case document chunks."""
import hashlib
import json
import logging
import re
import os
import stat
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5
from zipfile import ZipFile

from fastapi import HTTPException

from app.database import connection
from app.document_processing.text_chunker import chunk_text
from app.services.presentation_access import HAA_SCOPE
from app.services.cims_service import (
    DOCUMENT_READ, _current_assignment, _store, authorize_case, read_case_fields,
)

COLLECTION = "cims_case_documents"
MAX_BYTES = 50 * 1024 * 1024
PIPELINE = "1"
logger = logging.getLogger(__name__)


def manifests():
    return _store(connection.db["cims_documents"] if connection.db is not None else None)


def _units(path, digest):
    with path.open("rb") as source:
        signature = source.read(5)
    if signature == b"%PDF-":
        from app.ocr.document_ocr import run_document_ocr

        result = run_document_ocr(str(path), digest, "document.pdf", "application/pdf")
        return [(page["page_number"], page["text"]) for page in result.get("pages", [])]

    with ZipFile(path) as archive:
        entries = archive.infolist()
        if (
            len(entries) > 5000
            or sum(entry.file_size for entry in entries) > MAX_BYTES
            or not {"[Content_Types].xml", "word/document.xml"}.issubset(archive.namelist())
        ):
            raise ValueError("Invalid Word package.")
    from docx import Document

    document = Document(path)
    blocks = [paragraph.text for paragraph in document.paragraphs]
    blocks.extend(" | ".join(cell.text for cell in row.cells)
                  for table in document.tables for row in table.rows)
    return list(enumerate(blocks, 1))


def _index(case_id, document_id, identity, data, metadata_name, stamp):
    from acc_statements.index import config, embed, get_client
    from qdrant_client import models

    digest = hashlib.sha256(data).hexdigest()
    version = str(uuid5(NAMESPACE_URL, f"{identity}:{digest}:{PIPELINE}"))
    published_fields = {
        "case_id": case_id, "document_id": document_id, "published_version": version,
        "status": "published", "metadata_name": metadata_name,
        "source_stamp": list(stamp), "pipeline": PIPELINE,
    }
    existing = manifests().find_one({"_id": identity}, {"published_version": 1})
    if existing and existing.get("published_version") == version:
        manifests().update_one({"_id": identity}, {"$set": published_fields,
            "$unset": {"failure_type": "", "failure_count": "", "retry_after": "", "failed_stamp": ""},
        })
        return

    with tempfile.TemporaryDirectory() as directory:
        staged = Path(directory) / "document"
        staged.write_bytes(data)
        chunks = [
            (locator, chunk["chunk_id"], chunk["text"])
            for locator, value in _units(staged, digest)
            for chunk in chunk_text(value, chunk_size=1200, overlap=50)
        ]
    if not chunks:
        raise ValueError("Document contains no extractable text.")

    client = get_client()
    if not client.collection_exists(COLLECTION):
        client.create_collection(
            COLLECTION, vectors_config=models.VectorParams(
                size=config.EMBED_DIM, distance=models.Distance.COSINE,
            ),
        )
    for offset in range(0, len(chunks), 32):
        batch = chunks[offset:offset + 32]
        vectors = embed([chunk[2] for chunk in batch])
        client.upsert(COLLECTION, wait=True, points=[
            models.PointStruct(
                id=str(uuid5(NAMESPACE_URL, f"{version}:{locator}:{chunk_id}")),
                vector=vector,
                payload={
                    "case_id": case_id, "document_id": document_id,
                    "version": version, "locator": locator, "chunk_id": chunk_id,
                    "text": value, "source_type": "cims_document",
                },
            )
            for (locator, chunk_id, value), vector in zip(batch, vectors, strict=True)
        ])
    version_filter = models.Filter(must=[
        models.FieldCondition(key="case_id", match=models.MatchValue(value=case_id)),
        models.FieldCondition(key="version", match=models.MatchValue(value=version)),
    ])
    if client.count(COLLECTION, count_filter=version_filter, exact=True).count != len(chunks):
        raise RuntimeError("Indexed chunk count does not match extracted chunks.")
    manifests().update_one({"_id": identity}, {"$set": published_fields,
        "$unset": {"failure_type": "", "failure_count": "", "retry_after": "", "failed_stamp": ""},
    }, upsert=True)


def _documents(case_id, assignment=None):
    assignment = assignment if assignment is not None else _current_assignment(case_id)
    if assignment is None:
        return []
    return read_case_fields(case_id, assignment, ("documents",)).get("documents") or []


@contextmanager
def _open_directory(path, parent=None):
    descriptor = os.open(
        path, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY, dir_fd=parent,
    )
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def _file_stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _reconcile_case(directory, case_id, observed, current):
    filenames = {
        name for name in os.listdir(directory)
        if stat.S_ISREG(os.stat(name, dir_fd=directory, follow_symlinks=False).st_mode)
    }
    matches = {}
    for item in _documents(case_id):
        prefix = item["document_id"] + "_"
        matched_names = {
            name for name in filenames if name.startswith(prefix) and len(name) > len(prefix)
        }
        for name in matched_names:
            matches.setdefault(name, []).append((item, len(matched_names) == 1))

    for name in sorted(filenames):
        candidates = matches.get(name, [])
        pending_key = str(uuid5(NAMESPACE_URL, json.dumps(["pending", case_id, name])))
        if len(candidates) != 1 or not candidates[0][1]:
            manifests().update_one({"_id": pending_key}, {"$set": {
                "case_id": case_id,
                "status": "ambiguous_match" if candidates else "pending_metadata",
            }}, upsert=True)
            continue

        metadata = candidates[0][0]
        document_id = metadata["document_id"]
        identity = str(uuid5(NAMESPACE_URL, json.dumps([case_id, document_id])))
        stamp = None
        work = None
        try:
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            with os.fdopen(os.open(name, flags, dir_fd=directory), "rb") as source:
                before = os.fstat(source.fileno())
                stamp = _file_stamp(before)
                key = (case_id, name)
                current[key] = stamp
                if observed.get(key) != stamp or not stat.S_ISREG(before.st_mode):
                    continue
                work = manifests().find_one({"_id": identity}) or {}
                if (
                    work.get("status") == "published" and work.get("source_stamp") == list(stamp)
                    and work.get("metadata_name") == metadata["file_name"] and work.get("pipeline") == PIPELINE
                ):
                    continue
                retry_after = work.get("retry_after")
                if (
                    work.get("failed_stamp") == list(stamp) and retry_after
                    and retry_after.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)
                ):
                    continue
                if before.st_size > MAX_BYTES:
                    raise ValueError("Document exceeds the staging limit.")
                data = source.read(MAX_BYTES + 1)
                if len(data) != before.st_size or stamp != _file_stamp(os.fstat(source.fileno())):
                    continue
            _index(case_id, document_id, identity, data, metadata["file_name"], stamp)
            manifests().delete_one({"_id": pending_key})
        except Exception as exc:
            failures = 1
            if work and stamp and work.get("failed_stamp") == list(stamp):
                failures = min(8, work.get("failure_count", 0) + 1)
            manifests().update_one({"_id": identity}, {"$set": {
                "case_id": case_id, "document_id": document_id, "status": "failed",
                "failure_type": type(exc).__name__, "failure_count": failures,
                "failed_stamp": list(stamp) if stamp else None,
                "retry_after": datetime.now(timezone.utc) + timedelta(seconds=30 * 2 ** failures),
            }}, upsert=True)
            logger.warning("CIMS document reconciliation failed (%s)", type(exc).__name__)


def reconcile(root, observed):
    """Run in the API's Qdrant-owning process, one scan at a time."""
    current = {}
    with _open_directory(root) as root_descriptor:
        for case_id in os.listdir(root_descriptor):
            try:
                directory = os.stat(case_id, dir_fd=root_descriptor, follow_symlinks=False)
                if stat.S_ISDIR(directory.st_mode):
                    with _open_directory(case_id, root_descriptor) as descriptor:
                        _reconcile_case(descriptor, case_id, observed, current)
            except FileNotFoundError:
                continue
            except PermissionError:
                logger.warning("CIMS sync skipped an unreadable case directory")
                continue
    return current


def _published_versions(session, case_id):
    assignment = authorize_case(session, case_id, DOCUMENT_READ)
    allowed = {(item["document_id"], item["file_name"]) for item in _documents(case_id, assignment)}
    if not allowed:
        return []
    versions = manifests().find({
        "case_id": case_id, "document_id": {"$in": sorted({item[0] for item in allowed})},
        "published_version": {"$exists": True},
    }, {"published_version": 1, "metadata_name": 1, "document_id": 1})
    return [
        item["published_version"] for item in versions
        if (item["document_id"], item.get("metadata_name")) in allowed
    ]


def conversation_message_scope(session, conversation):
    case_id = conversation.get("case_id")
    mode = conversation.get("case_mode", "metadata")
    if case_id in {None, HAA_SCOPE} or mode not in {"metadata", "documents"}:
        return {}
    try:
        versions = _published_versions(session, case_id)
    except HTTPException as exc:
        if exc.status_code != 403 or mode == "documents":
            raise
        versions = []
    return {"source_versions": {"$not": {"$elemMatch": {"$nin": versions}}}}


def search_case_documents(session, case_id, query):
    from acc_statements.index import embed, get_client
    from qdrant_client import models

    allowed_versions = _published_versions(session, case_id)
    if not allowed_versions:
        return []
    client = get_client()
    if not client.collection_exists(COLLECTION):
        raise HTTPException(503, "Case document search is unavailable.")
    query_filter = models.Filter(must=[
        models.FieldCondition(key="case_id", match=models.MatchValue(value=case_id)),
        models.FieldCondition(key="version", match=models.MatchAny(any=allowed_versions)),
    ])
    questions = [query]
    if is_case_overview(query):
        questions.extend([
            "Purpose, scope and background of the investigation, recorded allegations and case assignment",
            "People and organizations involved, their roles, key events, amounts and documented findings",
        ])
    ranked_lists = [
        client.query_points(
            COLLECTION, query=vector, limit=5, with_payload=True, query_filter=query_filter,
        ).points
        for vector in embed(questions)
    ]
    hits = {}
    for rank in range(5):
        for points in ranked_lists:
            if rank >= len(points):
                continue
            point = points[rank]
            payload = point.payload or {}
            if payload.get("case_id") == case_id and payload.get("version") in allowed_versions:
                hits.setdefault(str(point.id), {**payload, "point_id": str(point.id)})
    return list(hits.values())[:8]


def is_case_overview(query):
    first_line = query.splitlines()[0]
    return bool(re.search(
        r"\b(?:summari[sz]e|summar[yi]|overview|tell me about (?:the )?case|"
        r"what (?:is|was) (?:the )?case\b.{0,35}\babout)\b",
        first_line, re.IGNORECASE,
    ))


def read_source_excerpt(session, case_id, point_id):
    from acc_statements.index import get_client
    from qdrant_client import models

    allowed_versions = _published_versions(session, case_id)
    try:
        point_id = str(UUID(point_id))
    except ValueError:
        raise HTTPException(404, "Source not found.") from None
    if allowed_versions:
        points, _ = get_client().scroll(
            COLLECTION, limit=1, with_payload=True,
            scroll_filter=models.Filter(must=[
                models.HasIdCondition(has_id=[point_id]),
                models.FieldCondition(key="case_id", match=models.MatchValue(value=case_id)),
                models.FieldCondition(key="version", match=models.MatchAny(any=allowed_versions)),
            ]),
        )
        if points:
            payload = points[0].payload or {}
            if payload.get("case_id") == case_id and payload.get("version") in allowed_versions:
                return {"text": payload["text"], "sentences": []}
    raise HTTPException(404, "Source not found.")
