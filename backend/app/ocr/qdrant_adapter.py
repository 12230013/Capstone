"""Document-scoped OCR writes to the dedicated OCR collection."""

import importlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from app.document_processing.text_chunker import chunk_text
from app.ocr.layout import structured_chunks
from app.ocr.embedding import BGEEmbeddingAdapter


OCR_SOURCE_TYPE = "ocr_document"
_DOCUMENT_WRITE_LOCK = RLock()


class OCRVectorStoreError(RuntimeError):
    """Raised when OCR vectors cannot safely use the statement index."""


class OCRCollectionNotFoundError(OCRVectorStoreError):
    """Raised when the configured OCR collection does not exist."""


class OCRCollectionCompatibilityError(OCRVectorStoreError):
    """Raised when the OCR collection has an incompatible vector schema."""


class OCRVectorStoreConnectionError(OCRVectorStoreError):
    """Raised when the existing Qdrant client cannot complete an operation."""


class OCRQdrantAdapter:
    def __init__(
        self,
        client: Any | None = None,
        embedder: BGEEmbeddingAdapter | None = None,
        index_module: Any | None = None,
        qdrant_models: Any | None = None,
    ) -> None:
        self._client = client
        self._embedder = embedder or BGEEmbeddingAdapter()
        self._index_module = index_module
        self._qdrant_models = qdrant_models

    def upsert_document(
        self,
        document_result: Mapping[str, Any],
        case_no: str | None = None,
        owner_user_id: str | None = None,
    ) -> dict[str, Any]:
        owner_user_id = self._require_owner_user_id(owner_user_id)
        document_id, pages, filename = self._validate_document(
            document_result,
            case_no,
        )
        chunk_records = self._make_chunks(
            document_result,
            document_id,
            pages,
            filename,
            owner_user_id,
        )
        client, collection = self._client_and_collection()
        vectors = self._embedder.embed([record["text"] for record in chunk_records])
        points = [
            self._models().PointStruct(
                id=record["point_id"],
                vector=vector,
                payload=record["payload"],
            )
            for record, vector in zip(chunk_records, vectors)
        ]

        with _DOCUMENT_WRITE_LOCK:
            existing_points = self._scroll_document(
                client,
                collection,
                document_id,
                owner_user_id,
                with_payload=False,
            )
            active_ids = {point.id for point in points}
            existing_ids = {point.id for point in existing_points}
            stale_ids = existing_ids - active_ids

            self._run_qdrant(
                "upsert OCR document vectors",
                lambda: client.upsert(
                    collection_name=collection,
                    points=points,
                    wait=True,
                ),
            )
            if stale_ids:
                self._delete_point_ids(client, collection, sorted(stale_ids))

        return {
            "document_id": document_id,
            "collection": collection,
            "chunks_upserted": len(points),
            "stale_chunks_deleted": len(stale_ids),
        }

    def get_document_metadata(
        self,
        document_id: str,
        owner_user_id: str,
    ) -> list[dict[str, Any]]:
        document_id = self._validate_document_id(document_id)
        owner_user_id = self._require_owner_user_id(owner_user_id)
        client, collection = self._client_and_collection()
        points = self._scroll_document(
            client,
            collection,
            document_id,
            owner_user_id,
            with_payload=True,
        )
        return [dict(point.payload or {}) for point in points]

    def retrieve_document(
        self,
        query: str,
        document_id: str,
        owner_user_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        document_id = self._validate_document_id(document_id)
        if not isinstance(owner_user_id, str) or not owner_user_id.strip():
            raise ValueError("An owner user ID is required for OCR retrieval.")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("An OCR retrieval query is required.")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("OCR retrieval limit must be a positive integer.")

        return self.retrieve_documents(query, [document_id], owner_user_id, limit)

    def retrieve_documents(self, query: str, document_ids: list[str], owner_user_id: str, limit: int = 5) -> list[dict[str, Any]]:
        owner_user_id = self._require_owner_user_id(owner_user_id)
        document_ids = [self._validate_document_id(d) for d in document_ids]
        if not document_ids:
            return []
        client, collection = self._client_and_collection()
        query_vector = self._embedder.embed([query])[0]
        models = self._models()
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="source_type",
                    match=models.MatchValue(value=OCR_SOURCE_TYPE),
                ),
                models.FieldCondition(
                    key="owner_user_id",
                    match=models.MatchValue(value=owner_user_id.strip()),
                ),
                models.FieldCondition(
                    key="document_id",
                    match=(models.MatchValue(value=document_ids[0]) if len(document_ids) == 1 else models.MatchAny(any=document_ids)),
                ),
            ]
        )
        response = self._run_qdrant(
            "retrieve owner-scoped OCR document vectors",
            lambda: client.query_points(
                collection_name=collection,
                query=query_vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            ),
        )

        chunks = []
        for point in response.points:
            payload = getattr(point, "payload", None)
            if not isinstance(payload, dict):
                continue
            if (
                payload.get("source_type") != OCR_SOURCE_TYPE
                or payload.get("owner_user_id") != owner_user_id.strip()
                or payload.get("document_id") not in document_ids
            ):
                continue
            text = payload.get("text_numbered")
            if not isinstance(text, str) or not text.strip():
                continue
            chunks.append(
                {
                    "text": text,
                    "score": getattr(point, "score", None),
                    "metadata": {"metadata": payload},
                }
            )
        return chunks

    def delete_document(self, document_id: str, owner_user_id: str) -> int:
        document_id = self._validate_document_id(document_id)
        owner_user_id = self._require_owner_user_id(owner_user_id)
        with _DOCUMENT_WRITE_LOCK:
            client, collection = self._client_and_collection()
            points = self._scroll_document(
                client,
                collection,
                document_id,
                owner_user_id,
                with_payload=False,
            )
            point_ids = [point.id for point in points]
            if point_ids:
                self._delete_point_ids(client, collection, point_ids)
        return len(point_ids)

    def provision_collection(self) -> str:
        """Create the OCR collection explicitly, or validate it if it exists."""
        index, config = self._index_and_config()
        client = self._get_client(index, config)
        collection = config.OCR_COLLECTION
        models = self._models()
        with _DOCUMENT_WRITE_LOCK:
            exists = self._run_qdrant(
                "check whether the OCR collection exists",
                lambda: client.collection_exists(collection_name=collection),
            )
            if not exists:
                self._run_qdrant(
                    "provision the OCR collection",
                    lambda: client.create_collection(
                        collection_name=collection,
                        vectors_config=models.VectorParams(
                            size=config.EMBED_DIM,
                            distance=models.Distance.COSINE,
                        ),
                    ),
                )
            self._validate_collection(client, collection)
        return collection

    def _validate_document(
        self,
        result: Mapping[str, Any],
        case_no: str | None,
    ) -> tuple[str, list[Mapping[str, Any]], str]:
        if not isinstance(result, Mapping):
            raise ValueError("OCR result must be a mapping.")
        document_id = self._validate_document_id(result.get("document_id"))
        raw_pages = result.get("pages")
        if not isinstance(raw_pages, list):
            raise ValueError("OCR result pages must be a list.")

        pages = []
        for page in raw_pages:
            if not isinstance(page, Mapping):
                raise ValueError("Every OCR page must be a mapping.")
            page_number = page.get("page_number")
            if (
                not isinstance(page_number, int)
                or isinstance(page_number, bool)
                or page_number < 1
            ):
                raise ValueError("Every OCR page must have a positive page number.")
            text = page.get("text")
            if not isinstance(text, str):
                raise ValueError("Every OCR page must contain text.")
            pages.append(page)
        if not pages:
            raise ValueError("OCR result must contain at least one page.")

        filename = result.get("filename")
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("OCR result must contain a source filename.")

        if case_no is not None and (
            not isinstance(case_no, str) or case_no.strip()
        ):
            raise ValueError(
                "Case-linked OCR indexing is not available without authorization."
            )
        return document_id, pages, filename.strip()

    @staticmethod
    def _require_owner_user_id(owner_user_id: Any) -> str:
        if not isinstance(owner_user_id, str) or not owner_user_id.strip():
            raise ValueError("An owner user ID is required for OCR operations.")
        return owner_user_id.strip()

    @staticmethod
    def _validate_document_id(document_id: Any) -> str:
        if not isinstance(document_id, str) or not document_id.strip():
            raise ValueError("OCR document_id must be a non-empty string.")
        return document_id.strip()

    @staticmethod
    def _make_chunks(
        result: Mapping[str, Any],
        document_id: str,
        pages: list[Mapping[str, Any]],
        filename: str,
        owner_user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        ingestion_timestamp = datetime.now(timezone.utc).isoformat()
        chunks = []
        for page in pages:
            page_number = page["page_number"]
            page_chunks = chunk_text(
                page["text"],
                chunk_size=1200,
                overlap=50,
            )
            if page.get("blocks"):
                page_chunks = structured_chunks(page["blocks"])
            for page_chunk in page_chunks:
                chunk_id = f"p{page_number}-c{page_chunk['chunk_id']}"
                payload = {
                    "doc_id": document_id,
                    "document_id": document_id,
                    "source_type": OCR_SOURCE_TYPE,
                    "filename": filename,
                    "page_number": page_number,
                    "chunk_id": chunk_id,
                    "sentence_ids": [],
                    "text_numbered": page_chunk["text"],
                    "ingestion_timestamp": ingestion_timestamp,
                }
                if isinstance(result.get("case_number"), str) and result["case_number"].strip():
                    payload["case_number"] = result["case_number"].strip()
                if owner_user_id is not None:
                    payload["owner_user_id"] = owner_user_id

                extraction_method = page.get(
                    "extraction_method",
                    result.get("extraction_method"),
                )
                if isinstance(extraction_method, str) and extraction_method.strip():
                    payload["extraction_method"] = extraction_method.strip()

                confidence = page.get("confidence")
                if confidence is not None:
                    if (
                        isinstance(confidence, bool)
                        or not isinstance(confidence, (int, float))
                        or not math.isfinite(float(confidence))
                    ):
                        raise ValueError("OCR confidence must be a finite number.")
                    payload["confidence"] = float(confidence)

                quality = page.get(
                    "quality_decision",
                    result.get("quality_decision"),
                )
                if isinstance(quality, str) and quality.strip():
                    payload["document_quality"] = quality.strip()

                for metadata_key in (
                    "ocr_engine",
                    "ocr_model",
                    "ocr_status",
                ):
                    metadata_value = result.get(metadata_key)
                    if isinstance(metadata_value, str) and metadata_value.strip():
                        payload[metadata_key] = metadata_value.strip()

                json.dumps(payload, allow_nan=False)
                point_id = str(
                    uuid5(
                        NAMESPACE_URL,
                        f"acc-ocr:{document_id}:{chunk_id}",
                    )
                )
                chunks.append(
                    {
                        "point_id": point_id,
                        "text": page_chunk["text"],
                        "payload": payload,
                    }
                )
        if not chunks:
            raise ValueError("OCR result contains no non-empty text to index.")
        return chunks

    def _client_and_collection(self) -> tuple[Any, str]:
        index, config = self._index_and_config()
        client = self._get_client(index, config)
        collection = config.OCR_COLLECTION
        self._validate_collection(client, collection)
        return client, collection

    def _index_and_config(self) -> tuple[Any, Any]:
        index = self._index()
        config = index.config
        if (
            config.COLLECTION != "statements"
            or not isinstance(config.OCR_COLLECTION, str)
            or not config.OCR_COLLECTION.strip()
            or config.OCR_COLLECTION == config.COLLECTION
        ):
            raise OCRCollectionCompatibilityError(
                "OCR must use a dedicated collection distinct from 'statements'."
            )
        if config.EMBED_MODEL != "BAAI/bge-m3" or config.EMBED_DIM != 1024:
            raise OCRCollectionCompatibilityError(
                "The shared index must use 1024-dimensional BAAI/bge-m3 vectors."
            )
        return index, config

    def _get_client(self, index: Any, config: Any) -> Any:
        if self._client is not None:
            return self._client
        if not Path(config.QDRANT_PATH).exists():
            raise OCRCollectionNotFoundError(
                "The configured Qdrant storage path does not exist; OCR will not "
                "initialize a new local database."
            )
        return self._run_qdrant(
            "connect to the existing Qdrant client",
            index.get_client,
        )

    def _validate_collection(self, client: Any, collection: str) -> None:
        try:
            info = self._run_qdrant(
                "inspect the OCR collection",
                lambda: client.get_collection(collection_name=collection),
            )
        except ValueError as exc:
            if "not found" in str(exc).lower():
                raise OCRCollectionNotFoundError(
                    f"The OCR collection '{collection}' is not available; "
                    "OCR uploads will not create it."
                ) from exc
            raise

        params = getattr(getattr(info, "config", None), "params", None)
        vectors = getattr(params, "vectors", None)
        vector_size = getattr(vectors, "size", None)
        vector_distance = getattr(vectors, "distance", None)
        vector_distance = getattr(vector_distance, "value", vector_distance)
        if vector_size != 1024 or str(vector_distance).lower() != "cosine":
            raise OCRCollectionCompatibilityError(
                f"The OCR collection '{collection}' must use 1024-dimensional "
                "cosine vectors; its schema was left unchanged."
            )

    def _scroll_document(
        self,
        client: Any,
        collection: str,
        document_id: str,
        owner_user_id: str,
        with_payload: bool,
    ) -> list[Any]:
        models = self._models()
        scroll_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="source_type",
                    match=models.MatchValue(value=OCR_SOURCE_TYPE),
                ),
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=document_id),
                ),
                models.FieldCondition(
                    key="owner_user_id",
                    match=models.MatchValue(value=owner_user_id),
                ),
            ]
        )
        points = []
        offset = None
        while True:
            batch, offset = self._run_qdrant(
                "read OCR document points",
                lambda: client.scroll(
                    collection_name=collection,
                    scroll_filter=scroll_filter,
                    limit=256,
                    offset=offset,
                    with_payload=with_payload,
                    with_vectors=False,
                ),
            )
            points.extend(batch)
            if offset is None:
                return points

    def _delete_point_ids(
        self,
        client: Any,
        collection: str,
        point_ids: list[Any],
    ) -> None:
        self._run_qdrant(
            "delete OCR document points",
            lambda: client.delete(
                collection_name=collection,
                points_selector=self._models().PointIdsList(points=point_ids),
                wait=True,
            ),
        )

    def _index(self) -> Any:
        if self._index_module is not None:
            return self._index_module
        try:
            self._index_module = importlib.import_module("acc_statements.index")
        except ImportError as exc:
            raise OCRVectorStoreError(
                "The existing ACC statements index is unavailable."
            ) from exc
        return self._index_module

    def _models(self) -> Any:
        if self._qdrant_models is not None:
            return self._qdrant_models
        try:
            self._qdrant_models = importlib.import_module("qdrant_client.models")
        except ImportError as exc:
            raise OCRVectorStoreError(
                "The Qdrant client dependency is unavailable."
            ) from exc
        return self._qdrant_models

    @staticmethod
    def _run_qdrant(operation: str, callback: Any) -> Any:
        try:
            return callback()
        except _qdrant_connection_errors() as exc:
            raise OCRVectorStoreConnectionError(
                f"Could not {operation} using the existing Qdrant client."
            ) from exc


def _qdrant_connection_errors() -> tuple[type[BaseException], ...]:
    errors: list[type[BaseException]] = [
        ConnectionError,
        TimeoutError,
        OSError,
        RuntimeError,
    ]
    try:
        from httpx import TransportError
    except ImportError:
        pass
    else:
        errors.append(TransportError)
    try:
        from qdrant_client.http.exceptions import ResponseHandlingException
    except ImportError:
        pass
    else:
        errors.append(ResponseHandlingException)
    return tuple(errors)
