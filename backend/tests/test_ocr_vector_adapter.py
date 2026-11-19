import importlib
import json
import os
import sys
import tempfile
import types
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.ocr.embedding import (
    BGEEmbeddingAdapter,
    EMBEDDING_DIMENSION,
    EmbeddingError,
)
from app.ocr.qdrant_adapter import (
    OCRCollectionCompatibilityError,
    OCRCollectionNotFoundError,
    OCRQdrantAdapter,
    OCRVectorStoreConnectionError,
)


class FakeMatchValue:
    def __init__(self, value):
        self.value = value


class FakeFieldCondition:
    def __init__(self, key, match):
        self.key = key
        self.match = match


class FakeFilter:
    def __init__(self, must=None, must_not=None):
        self.must = must
        self.must_not = must_not


class FakePointStruct:
    def __init__(self, id, vector, payload):
        self.id = id
        self.vector = vector
        self.payload = payload


class FakeVectorParams:
    def __init__(self, size, distance):
        self.size = size
        self.distance = distance


class FakeDistance:
    COSINE = "Cosine"


class FakePointIdsList:
    def __init__(self, points):
        self.points = points


class FakeQdrantModels:
    Filter = FakeFilter
    FieldCondition = FakeFieldCondition
    MatchValue = FakeMatchValue
    PointStruct = FakePointStruct
    PointIdsList = FakePointIdsList
    VectorParams = FakeVectorParams
    Distance = FakeDistance


class FakePoint:
    def __init__(self, point_id, payload, vector=None):
        self.id = point_id
        self.payload = payload
        self.vector = vector


class FakeQdrantClient:
    def __init__(self, vector_size=1024, distance="Cosine"):
        self.points = {}
        self.vector_size = vector_size
        self.distance = distance
        self.collection_present = True
        self.get_collection_calls = []
        self.collection_exists_calls = []
        self.create_collection_calls = []
        self.delete_collection_calls = []
        self.recreate_collection_calls = []
        self.upsert_calls = []
        self.delete_calls = []
        self.scroll_calls = []
        self.query_calls = []
        self.fail_get_collection = None

    def get_collection(self, collection_name):
        self.get_collection_calls.append(collection_name)
        if self.fail_get_collection:
            raise self.fail_get_collection
        return types.SimpleNamespace(
            config=types.SimpleNamespace(
                params=types.SimpleNamespace(
                    vectors=types.SimpleNamespace(
                        size=self.vector_size,
                        distance=self.distance,
                    )
                )
            )
        )

    def upsert(self, collection_name, points, wait):
        self.upsert_calls.append((collection_name, points, wait))
        for point in points:
            self.points[point.id] = point

    def create_collection(self, *args, **kwargs):
        self.create_collection_calls.append((args, kwargs))
        self.collection_present = True
        vectors_config = kwargs.get("vectors_config")
        if vectors_config is not None:
            self.vector_size = vectors_config.size
            self.distance = vectors_config.distance

    def collection_exists(self, collection_name):
        self.collection_exists_calls.append(collection_name)
        return self.collection_present

    def delete_collection(self, *args, **kwargs):
        self.delete_collection_calls.append((args, kwargs))

    def recreate_collection(self, *args, **kwargs):
        self.recreate_collection_calls.append((args, kwargs))

    def scroll(
        self,
        collection_name,
        scroll_filter,
        limit,
        offset,
        with_payload,
        with_vectors,
    ):
        self.scroll_calls.append(
            (
                collection_name,
                scroll_filter,
                limit,
                offset,
                with_payload,
                with_vectors,
            )
        )
        matches = [
            point
            for point in self.points.values()
            if all(
                point.payload.get(condition.key) == condition.match.value
                for condition in scroll_filter.must
            )
        ]
        start = offset or 0
        batch = matches[start : start + limit]
        next_offset = start + limit if start + limit < len(matches) else None
        batch = [
            FakePoint(
                point.id,
                deepcopy(point.payload) if with_payload else {},
                deepcopy(point.vector) if with_vectors else None,
            )
            for point in batch
        ]
        return batch, next_offset

    def delete(self, collection_name, points_selector, wait):
        self.delete_calls.append((collection_name, points_selector.points, wait))
        for point_id in points_selector.points:
            self.points.pop(point_id, None)

    def query_points(
        self,
        collection_name,
        query,
        query_filter,
        limit,
        with_payload,
    ):
        self.query_calls.append(
            (collection_name, query, query_filter, limit, with_payload)
        )
        matches = [
            point
            for point in self.points.values()
            if all(
                point.payload.get(condition.key) == condition.match.value
                for condition in query_filter.must
            )
        ][:limit]
        scored_points = [
            types.SimpleNamespace(
                id=point.id,
                payload=deepcopy(point.payload) if with_payload else {},
                score=0.9,
            )
            for point in matches
        ]
        return types.SimpleNamespace(points=scored_points)


class EmbeddingAdapterTests(unittest.TestCase):
    def test_uses_existing_index_embedder_and_normalizes_batch_text(self):
        calls = []
        fake_index = types.ModuleType("acc_statements.index")
        fake_index.config = types.SimpleNamespace(
            EMBED_MODEL="BAAI/bge-m3",
            EMBED_DIM=EMBEDDING_DIMENSION,
        )
        fake_index.embed = lambda texts: (
            calls.append(texts) or [[0.25] * EMBEDDING_DIMENSION for _ in texts]
        )

        with patch.dict(sys.modules, {"acc_statements.index": fake_index}):
            vectors = BGEEmbeddingAdapter().embed(["  first \n text ", "second"])

        self.assertEqual(calls, [["first text", "second"]])
        self.assertEqual(len(vectors), 2)
        self.assertTrue(all(len(vector) == EMBEDDING_DIMENSION for vector in vectors))

    def test_empty_batch_is_supported_but_empty_text_is_rejected(self):
        adapter = BGEEmbeddingAdapter(lambda texts: [])
        self.assertEqual(adapter.embed([]), [])
        with self.assertRaises(ValueError):
            adapter.embed([" \t "])
        with self.assertRaises(ValueError):
            adapter.embed([None])

    def test_invalid_dimension_and_non_finite_values_are_rejected(self):
        with self.assertRaises(EmbeddingError):
            BGEEmbeddingAdapter(lambda texts: [[1.0, 2.0]]).embed(["text"])

        with self.assertRaises(EmbeddingError):
            BGEEmbeddingAdapter(lambda texts: []).embed(["text"])

        invalid_vector = [1.0] * EMBEDDING_DIMENSION
        invalid_vector[-1] = float("nan")
        with self.assertRaises(EmbeddingError):
            BGEEmbeddingAdapter(lambda texts: [invalid_vector]).embed(["text"])

    def test_shared_embedding_errors_are_reported(self):
        def fail(texts):
            raise RuntimeError("model unavailable")

        with self.assertRaises(EmbeddingError):
            BGEEmbeddingAdapter(fail).embed(["text"])


class QdrantAdapterTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeQdrantClient()
        self.index = types.SimpleNamespace(
            config=types.SimpleNamespace(
                COLLECTION="statements",
                OCR_COLLECTION="ocr_documents",
                EMBED_MODEL="BAAI/bge-m3",
                EMBED_DIM=EMBEDDING_DIMENSION,
                QDRANT_PATH=str(Path(__file__).parent),
            ),
            get_client=lambda: self.client,
        )
        self.embedder = BGEEmbeddingAdapter(
            lambda texts: [[0.5] * EMBEDDING_DIMENSION for _ in texts]
        )
        self.build_index_calls = []
        self.index.build_index = lambda: self.build_index_calls.append(True)
        self.adapter = OCRQdrantAdapter(
            client=self.client,
            embedder=self.embedder,
            index_module=self.index,
            qdrant_models=FakeQdrantModels,
        )

    @staticmethod
    def document(document_id="ocr-doc-1", pages=None):
        return {
            "document_id": document_id,
            "filename": "bank-statement.pdf",
            "ocr_engine": "paddleocr",
            "ocr_model": "PP-OCRv5-mobile",
            "ocr_status": "completed",
            "quality_decision": "manual_review_recommended",
            "pages": pages
            if pages is not None
            else [
                {
                    "page_number": 1,
                    "text": "Account transfer recorded.",
                    "confidence": 92.5,
                    "extraction_method": "paddleocr",
                    "quality_decision": "manual_review_recommended",
                }
            ],
        }

    def test_document_writes_require_owner_user_id(self):
        with self.assertRaises(ValueError):
            self.adapter.upsert_document(self.document())

        self.assertEqual(self.client.get_collection_calls, [])
        self.assertEqual(self.client.upsert_calls, [])

    def test_metadata_and_deletion_require_owner_user_id(self):
        with self.assertRaises(ValueError):
            self.adapter.get_document_metadata("ocr-doc-1", "")
        with self.assertRaises(ValueError):
            self.adapter.delete_document("ocr-doc-1", "")

        self.assertEqual(self.client.get_collection_calls, [])
        self.assertEqual(self.client.scroll_calls, [])
        self.assertEqual(self.client.delete_calls, [])

    def test_owner_cannot_read_or_delete_another_owners_document(self):
        self.adapter.upsert_document(
            self.document(document_id="owner-a-document"),
            owner_user_id="owner-a",
        )
        self.adapter.upsert_document(
            self.document(document_id="owner-b-document"),
            owner_user_id="owner-b",
        )

        metadata = self.adapter.get_document_metadata(
            "owner-b-document", owner_user_id="owner-a"
        )
        deleted = self.adapter.delete_document(
            "owner-b-document", owner_user_id="owner-a"
        )

        self.assertEqual(metadata, [])
        self.assertEqual(deleted, 0)
        self.assertTrue(
            any(
                point.payload.get("owner_user_id") == "owner-b"
                for point in self.client.points.values()
            )
        )
        self.assertEqual(
            [(condition.key, condition.match.value)
             for condition in self.client.scroll_calls[-1][1].must],
            [
                ("source_type", "ocr_document"),
                ("document_id", "owner-b-document"),
                ("owner_user_id", "owner-a"),
            ],
        )

    def test_initialization_reuses_existing_collection_without_creating_it(self):
        result = self.adapter.upsert_document(
            self.document(), owner_user_id="owner-1"
        )
        self.assertEqual(result["collection"], "ocr_documents")
        self.assertEqual(self.client.get_collection_calls, ["ocr_documents"])
        self.assertEqual(self.client.create_collection_calls, [])
        self.assertEqual(self.client.delete_collection_calls, [])
        self.assertEqual(self.client.recreate_collection_calls, [])
        self.assertEqual(self.build_index_calls, [])

    def test_ocr_chunk_text_reaches_the_bge_callback_unchanged(self):
        expected_chunk = "OCR page: Account transfer of Nu 1,250.00 recorded on 2026-04-15."
        callback_texts = []
        embedder = BGEEmbeddingAdapter(
            lambda texts: (
                callback_texts.extend(texts)
                or [[0.5] * EMBEDDING_DIMENSION for _ in texts]
            )
        )
        adapter = OCRQdrantAdapter(
            client=self.client,
            embedder=embedder,
            index_module=self.index,
            qdrant_models=FakeQdrantModels,
        )

        adapter.upsert_document(
            self.document(
                pages=[{"page_number": 1, "text": expected_chunk}]
            ),
            owner_user_id="owner-1",
        )

        self.assertEqual(callback_texts, [expected_chunk])

    def test_owner_document_retrieval_filters_collection_owner_and_document(self):
        self.adapter.upsert_document(
            self.document("owned-doc"),
            owner_user_id="owner-1",
        )
        self.adapter.upsert_document(
            self.document("foreign-doc"),
            owner_user_id="owner-2",
        )

        chunks = self.adapter.retrieve_document(
            "transfer",
            document_id="owned-doc",
            owner_user_id="owner-1",
        )

        self.assertEqual(len(chunks), 1)
        self.assertEqual(
            chunks[0]["metadata"]["metadata"]["document_id"],
            "owned-doc",
        )
        self.assertEqual(
            chunks[0]["text"],
            "Account transfer recorded.",
        )
        collection, _query, query_filter, limit, with_payload = (
            self.client.query_calls[-1]
        )
        self.assertEqual(collection, "ocr_documents")
        self.assertEqual(limit, 5)
        self.assertTrue(with_payload)
        self.assertEqual(
            {
                condition.key: condition.match.value
                for condition in query_filter.must
            },
            {
                "source_type": "ocr_document",
                "owner_user_id": "owner-1",
                "document_id": "owned-doc",
            },
        )

    def test_invalid_vectors_never_upsert_or_delete_qdrant_points(self):
        invalid_vector_values = []
        for value in (float("inf"), float("-inf"), float("nan"), "not-a-number"):
            vector = [0.25] * EMBEDDING_DIMENSION
            vector[-1] = value
            invalid_vector_values.append((f"invalid value {value!r}", [vector]))

        invalid_results = [
            *invalid_vector_values,
            ("incorrect dimensions", [[0.25] * (EMBEDDING_DIMENSION - 1)]),
            ("incorrect vector count", []),
        ]
        for description, vectors in invalid_results:
            with self.subTest(result=description):
                client = FakeQdrantClient()
                existing_id = str(
                    uuid5(NAMESPACE_URL, "acc-ocr:ocr-doc-1:p1-c1")
                )
                existing_point = FakePoint(
                    existing_id,
                    {
                        "source_type": "ocr_document",
                        "document_id": "ocr-doc-1",
                    },
                    [0.5] * EMBEDDING_DIMENSION,
                )
                client.points[existing_id] = existing_point
                embedder = BGEEmbeddingAdapter(lambda texts: vectors)
                adapter = OCRQdrantAdapter(
                    client=client,
                    embedder=embedder,
                    index_module=self.index,
                    qdrant_models=FakeQdrantModels,
                )

                with self.assertRaises(EmbeddingError):
                    adapter.upsert_document(
                        self.document(), owner_user_id="owner-1"
                    )

                self.assertEqual(client.upsert_calls, [])
                self.assertEqual(client.delete_calls, [])
                self.assertIs(client.points[existing_id], existing_point)

    def test_default_client_is_reused_from_the_existing_index(self):
        adapter = OCRQdrantAdapter(
            embedder=self.embedder,
            index_module=self.index,
            qdrant_models=FakeQdrantModels,
        )
        result = adapter.upsert_document(
            self.document(), owner_user_id="owner-1"
        )
        self.assertEqual(result["collection"], "ocr_documents")
        self.assertEqual(self.client.get_collection_calls, ["ocr_documents"])

    def test_explicit_provisioning_creates_and_validates_ocr_collection(self):
        self.client.collection_present = False

        collection = self.adapter.provision_collection()

        self.assertEqual(collection, "ocr_documents")
        self.assertEqual(self.client.collection_exists_calls, ["ocr_documents"])
        self.assertEqual(
            self.client.create_collection_calls[0][1]["collection_name"],
            "ocr_documents",
        )
        vectors_config = self.client.create_collection_calls[0][1]["vectors_config"]
        self.assertEqual(vectors_config.size, EMBEDDING_DIMENSION)
        self.assertEqual(vectors_config.distance, FakeDistance.COSINE)
        self.assertEqual(self.client.get_collection_calls, ["ocr_documents"])

    def test_ocr_upload_does_not_create_a_missing_collection(self):
        self.client.collection_present = False
        self.client.fail_get_collection = ValueError(
            "Collection ocr_documents not found"
        )

        with self.assertRaises(OCRCollectionNotFoundError):
            self.adapter.upsert_document(
                self.document(), owner_user_id="owner-1"
            )

        self.assertEqual(self.client.create_collection_calls, [])
        self.assertEqual(self.client.upsert_calls, [])

    def test_explicit_case_number_is_rejected_before_qdrant_write(self):
        with self.assertRaises(ValueError):
            self.adapter.upsert_document(
                self.document(),
                case_no=" ACC/2026/014 ",
                owner_user_id="owner-1",
            )
        self.assertEqual(self.client.upsert_calls, [])
        self.assertEqual(self.client.points, {})

    def test_result_case_number_is_ignored_and_not_written_to_payload(self):
        result = self.document()
        result["case_no"] = "ACC/2026/014"
        self.adapter.upsert_document(result, owner_user_id="owner-1")
        point = next(iter(self.client.points.values()))
        payload = point.payload

        self.assertEqual(payload["doc_id"], "ocr-doc-1")
        self.assertEqual(payload["document_id"], "ocr-doc-1")
        self.assertEqual(payload["source_type"], "ocr_document")
        self.assertNotIn("case_no", payload)
        self.assertEqual(payload["page_number"], 1)
        self.assertEqual(payload["chunk_id"], "p1-c1")
        self.assertEqual(payload["sentence_ids"], [])
        self.assertEqual(payload["text_numbered"], "Account transfer recorded.")
        self.assertEqual(payload["extraction_method"], "paddleocr")
        self.assertEqual(payload["confidence"], 92.5)
        self.assertEqual(
            payload["document_quality"],
            "manual_review_recommended",
        )
        self.assertEqual(payload["filename"], "bank-statement.pdf")
        self.assertEqual(payload["ocr_model"], "PP-OCRv5-mobile")
        self.assertIn("ingestion_timestamp", payload)
        self.assertEqual(len(point.vector), EMBEDDING_DIMENSION)
        json.dumps(payload, allow_nan=False)

    def test_missing_case_number_is_not_invented(self):
        self.adapter.upsert_document(self.document(), owner_user_id="owner-1")
        payload = next(iter(self.client.points.values())).payload
        self.assertNotIn("case_no", payload)

    def test_repeated_ingestion_upserts_deterministic_points(self):
        first = self.adapter.upsert_document(
            self.document(), owner_user_id="owner-1"
        )
        second = self.adapter.upsert_document(
            self.document(), owner_user_id="owner-1"
        )
        self.assertEqual(first["chunks_upserted"], 1)
        self.assertEqual(second["chunks_upserted"], 1)
        self.assertEqual(len(self.client.points), 1)
        self.assertEqual(len(self.client.upsert_calls), 2)

    def test_point_ids_use_document_scoped_uuid5_formula(self):
        first_id = "ocr-doc-1"
        second_id = "ocr-doc-2"
        first_result = self.adapter.upsert_document(
            self.document(document_id=first_id),
            owner_user_id="owner-1",
        )
        second_result = self.adapter.upsert_document(
            self.document(document_id=second_id),
            owner_user_id="owner-1",
        )

        expected_first_id = str(
            uuid5(NAMESPACE_URL, f"acc-ocr:{first_id}:p1-c1")
        )
        expected_second_id = str(
            uuid5(NAMESPACE_URL, f"acc-ocr:{second_id}:p1-c1")
        )
        self.assertEqual(first_result["chunks_upserted"], 1)
        self.assertEqual(second_result["chunks_upserted"], 1)
        self.assertIn(expected_first_id, self.client.points)
        self.assertIn(expected_second_id, self.client.points)
        self.assertNotEqual(expected_first_id, expected_second_id)
        self.assertEqual(
            self.client.points[expected_first_id].payload["chunk_id"],
            "p1-c1",
        )
        self.assertEqual(
            self.client.points[expected_second_id].payload["chunk_id"],
            "p1-c1",
        )

    def test_ocr_point_ids_do_not_overwrite_statement_point_ids(self):
        statement_point_id = str(
            uuid5(NAMESPACE_URL, "ocr-doc-1-chunk1")
        )
        statement_point = FakePoint(
            statement_point_id,
            {
                "doc_id": "ocr-doc-1",
                "source_type": "statement",
                "text_numbered": "Existing statement text.",
            },
            [0.125] * EMBEDDING_DIMENSION,
        )
        self.client.points[statement_point_id] = statement_point
        statement_snapshot = (
            statement_point.id,
            deepcopy(statement_point.vector),
            deepcopy(statement_point.payload),
        )

        self.adapter.upsert_document(self.document(), owner_user_id="owner-1")

        self.assertIs(self.client.points[statement_point_id], statement_point)
        self.assertEqual(
            (
                statement_point.id,
                statement_point.vector,
                statement_point.payload,
            ),
            statement_snapshot,
        )
        self.assertEqual(len(self.client.points), 2)

    def test_fresh_ingestion_does_not_delete_any_points(self):
        result = self.adapter.upsert_document(
            self.document(), owner_user_id="owner-1"
        )

        self.assertEqual(result["stale_chunks_deleted"], 0)
        self.assertEqual(self.client.delete_calls, [])

    def test_update_removes_only_stale_points_for_the_same_ocr_document(self):
        self.adapter.upsert_document(
            self.document(
                pages=[
                    {"page_number": 1, "text": "First page."},
                    {"page_number": 2, "text": "Second page."},
                ]
            ),
            owner_user_id="owner-1",
        )
        other_document_result = self.adapter.upsert_document(
            self.document(
                document_id="other-document",
                pages=[{"page_number": 1, "text": "Other OCR document."}],
            ),
            owner_user_id="owner-1",
        )
        other_document_id = str(
            uuid5(NAMESPACE_URL, "acc-ocr:other-document:p1-c1")
        )
        self.assertEqual(other_document_result["chunks_upserted"], 1)
        statement_id = "pre-existing-statement-point"
        statement_point = FakePoint(
            statement_id,
            {
                "source_type": "statement",
                "doc_id": "statement-1",
                "text_numbered": "Unrelated statement.",
            },
            [0.75] * EMBEDDING_DIMENSION,
        )
        self.client.points[statement_id] = statement_point
        retained_snapshots = {
            point_id: (
                self.client.points[point_id].id,
                deepcopy(self.client.points[point_id].vector),
                deepcopy(self.client.points[point_id].payload),
            )
            for point_id in (other_document_id, statement_id)
        }

        result = self.adapter.upsert_document(
            self.document(pages=[{"page_number": 1, "text": "Updated page."}]),
            owner_user_id="owner-1",
        )
        deleted_ids = self.client.delete_calls[-1][1]

        self.assertEqual(result["stale_chunks_deleted"], 1)
        self.assertEqual(len(self.client.delete_calls), 1)
        self.assertEqual(deleted_ids, [str(uuid5(NAMESPACE_URL, "acc-ocr:ocr-doc-1:p2-c1"))])
        self.assertNotIn(deleted_ids[0], self.client.points)
        self.assertIn(statement_id, self.client.points)
        self.assertIn(other_document_id, self.client.points)
        for point_id, snapshot in retained_snapshots.items():
            point = self.client.points[point_id]
            self.assertEqual(
                (point.id, point.vector, point.payload),
                snapshot,
            )
        latest_filter = self.client.scroll_calls[-1][1]
        self.assertEqual(
            [(condition.key, condition.match.value) for condition in latest_filter.must],
            [
                ("source_type", "ocr_document"),
                ("document_id", "ocr-doc-1"),
                ("owner_user_id", "owner-1"),
            ],
        )

    def test_explicit_deletion_requires_ocr_source_and_document_id(self):
        self.adapter.upsert_document(self.document(), owner_user_id="owner-1")
        other_ocr_id = str(
            uuid5(NAMESPACE_URL, "acc-ocr:other-document:p1-c1")
        )
        self.adapter.upsert_document(
            self.document(
                document_id="other-document",
                pages=[{"page_number": 1, "text": "Other OCR document."}],
            ),
            owner_user_id="owner-1",
        )
        statement_id = "same-document-id-statement"
        statement_point = FakePoint(
            statement_id,
            {
                "source_type": "statement",
                "document_id": "ocr-doc-1",
                "text_numbered": "Statement record.",
            },
            [0.625] * EMBEDDING_DIMENSION,
        )
        self.client.points[statement_id] = statement_point
        target_ids = {
            point_id
            for point_id, point in self.client.points.items()
            if point.payload.get("source_type") == "ocr_document"
            and point.payload.get("document_id") == "ocr-doc-1"
        }
        retained_snapshots = {
            point_id: (
                point.id,
                deepcopy(point.vector),
                deepcopy(point.payload),
            )
            for point_id, point in self.client.points.items()
            if point_id not in target_ids
        }

        metadata = self.adapter.get_document_metadata(
            "ocr-doc-1", owner_user_id="owner-1"
        )
        self.assertEqual(len(metadata), 1)
        self.assertEqual(metadata[0]["document_id"], "ocr-doc-1")
        self.assertEqual(self.adapter.delete_document("ocr-doc-1", "owner-1"), 1)

        deleted_ids = self.client.delete_calls[-1][1]
        self.assertEqual(set(deleted_ids), target_ids)
        self.assertEqual(
            [(condition.key, condition.match.value)
             for condition in self.client.scroll_calls[-1][1].must],
            [
                ("source_type", "ocr_document"),
                ("document_id", "ocr-doc-1"),
                ("owner_user_id", "owner-1"),
            ],
        )
        self.assertFalse(target_ids.intersection(self.client.points))
        self.assertIn(other_ocr_id, self.client.points)
        self.assertIn(statement_id, self.client.points)
        for point_id, snapshot in retained_snapshots.items():
            point = self.client.points[point_id]
            self.assertEqual((point.id, point.vector, point.payload), snapshot)

    def test_collection_schema_mismatch_fails_without_modifying_collection(self):
        for vector_size, distance in ((384, "Cosine"), (1024, "Dot")):
            with self.subTest(vector_size=vector_size, distance=distance):
                self.client.vector_size = vector_size
                self.client.distance = distance
                with self.assertRaises(OCRCollectionCompatibilityError):
                    self.adapter.upsert_document(
                        self.document(), owner_user_id="owner-1"
                    )
                self.assertEqual(self.client.upsert_calls, [])
                self.assertEqual(self.client.delete_collection_calls, [])
                self.assertEqual(self.client.create_collection_calls, [])

    def test_missing_collection_is_not_created(self):
        self.client.fail_get_collection = ValueError("Collection statements not found")
        with self.assertRaises(OCRCollectionNotFoundError):
            self.adapter.upsert_document(
                self.document(), owner_user_id="owner-1"
            )
        self.assertEqual(self.client.create_collection_calls, [])

    def test_absent_local_storage_is_not_initialized(self):
        self.index.config.QDRANT_PATH = str(
            Path(tempfile.gettempdir()) / f"missing-ocr-qdrant-{uuid4()}"
        )
        self.index.get_client = lambda: self.fail(
            "Must not construct a Qdrant client for a missing store."
        )
        adapter = OCRQdrantAdapter(
            embedder=self.embedder,
            index_module=self.index,
            qdrant_models=FakeQdrantModels,
        )
        with self.assertRaises(OCRCollectionNotFoundError):
            adapter.upsert_document(self.document(), owner_user_id="owner-1")

    def test_qdrant_connection_errors_are_reported(self):
        self.client.fail_get_collection = ConnectionError("offline")
        with self.assertRaises(OCRVectorStoreConnectionError):
            self.adapter.upsert_document(
                self.document(), owner_user_id="owner-1"
            )

    def test_failure_to_open_the_existing_qdrant_client_is_reported(self):
        def fail_to_connect():
            raise RuntimeError("local Qdrant storage is already open")

        self.index.get_client = fail_to_connect
        adapter = OCRQdrantAdapter(
            embedder=self.embedder,
            index_module=self.index,
            qdrant_models=FakeQdrantModels,
        )
        with self.assertRaises(OCRVectorStoreConnectionError):
            adapter.upsert_document(self.document(), owner_user_id="owner-1")

    def test_invalid_or_empty_ocr_documents_are_rejected_before_embedding(self):
        with self.assertRaises(ValueError):
            self.adapter.upsert_document(
                {"document_id": " ", "filename": "x.pdf", "pages": []},
                owner_user_id="owner-1",
            )
        with self.assertRaises(ValueError):
            self.adapter.upsert_document(
                self.document(pages=[{"page_number": 1, "text": "   "}]),
                owner_user_id="owner-1",
            )
        self.assertEqual(self.client.get_collection_calls, [])


class ExistingStatementSearchTests(unittest.TestCase):
    @staticmethod
    def statement_index():
        fake_qdrant = types.ModuleType("qdrant_client")
        fake_qdrant.QdrantClient = object
        fake_qdrant.models = FakeQdrantModels
        fake_sentence_transformers = types.ModuleType("sentence_transformers")
        fake_sentence_transformers.__path__ = []
        fake_sentence_transformers.SentenceTransformer = object

        sys.modules.pop("acc_statements.index", None)
        with patch.dict(
            sys.modules,
            {
                "qdrant_client": fake_qdrant,
                "sentence_transformers": fake_sentence_transformers,
            },
        ):
            return importlib.import_module("acc_statements.index")

    def test_existing_index_initializes_bge_once_and_batches_normalized_vectors(self):
        index = self.statement_index()
        constructor_calls = []
        encode_calls = []

        class FakeEmbeddings:
            def tolist(self):
                return [[1.0] * EMBEDDING_DIMENSION for _ in encode_calls[-1][0]]

        class FakeModel:
            def encode(self, texts, normalize_embeddings, batch_size):
                encode_calls.append((texts, normalize_embeddings, batch_size))
                return FakeEmbeddings()

        with (
            patch.object(index, "_embedder", None),
            patch.object(
                index,
                "SentenceTransformer",
                side_effect=lambda *args, **kwargs: (
                    constructor_calls.append((args, kwargs)) or FakeModel()
                ),
            ),
        ):
            first_model = index.get_embedder()
            second_model = index.get_embedder()
            vectors = index.embed(["first", "second"])

        self.assertIs(first_model, second_model)
        self.assertEqual(len(constructor_calls), 1)
        self.assertEqual(constructor_calls[0][0], ("BAAI/bge-m3",))
        self.assertEqual(constructor_calls[0][1]["device"], "cpu")
        self.assertEqual(
            encode_calls,
            [(["first", "second"], True, index.config.EMBED_BATCH)],
        )
        self.assertEqual(len(vectors), 2)
        self.assertTrue(all(len(vector) == EMBEDDING_DIMENSION for vector in vectors))

    @staticmethod
    def fake_model_modules():
        calls = {
            "transformer": [],
            "pooling": [],
            "normalize": [],
            "sentence_transformer": [],
        }

        class FakeTransformer:
            def __init__(self, model_path, **kwargs):
                calls["transformer"].append((model_path, kwargs))

        class FakePooling:
            @classmethod
            def load(cls, pooling_path):
                config_path = Path(pooling_path) / "config.json"
                pooling_config = json.loads(
                    config_path.read_text(encoding="utf-8")
                )
                calls["pooling"].append((pooling_path, pooling_config))
                enabled_modes = sum(
                    bool(pooling_config.get(key, False))
                    for key in (
                        "pooling_mode_cls_token",
                        "pooling_mode_mean_tokens",
                        "pooling_mode_max_tokens",
                        "pooling_mode_mean_sqrt_len_tokens",
                    )
                )
                class FakePoolingInstance:
                    def __init__(self):
                        self.pooling_config = pooling_config

                    def get_sentence_embedding_dimension(self):
                        return (
                            pooling_config["word_embedding_dimension"]
                            * enabled_modes
                        )

                return FakePoolingInstance()

        class FakeNormalize:
            @classmethod
            def load(cls, normalize_path):
                calls["normalize"].append(normalize_path)
                class FakeNormalizeInstance:
                    pass

                return FakeNormalizeInstance()

        fake_models = types.ModuleType("sentence_transformers.models")
        fake_models.Transformer = FakeTransformer
        fake_models.Pooling = FakePooling
        fake_models.Normalize = FakeNormalize
        return fake_models, calls

    @staticmethod
    def create_local_model(path):
        (path / "1_Pooling").mkdir(parents=True)
        (path / "config.json").write_text(
            json.dumps({"model_type": "xlm-roberta", "hidden_size": 1024}),
            encoding="utf-8",
        )
        (path / "sentence_bert_config.json").write_text(
            json.dumps({"max_seq_length": 8192, "do_lower_case": False}),
            encoding="utf-8",
        )
        (path / "modules.json").write_text(
            json.dumps(
                [
                    {
                        "name": "0",
                        "path": "",
                        "type": "sentence_transformers.models.Transformer",
                    },
                    {
                        "name": "1",
                        "path": "1_Pooling",
                        "type": "sentence_transformers.models.Pooling",
                    },
                    {
                        "name": "2",
                        "path": "2_Normalize",
                        "type": "sentence_transformers.models.Normalize",
                    },
                ]
            ),
            encoding="utf-8",
        )
        (path / "pytorch_model.bin").write_bytes(b"mock weights")
        (path / "tokenizer.json").write_text("{}", encoding="utf-8")
        (path / "1_Pooling" / "config.json").write_text(
            json.dumps(
                {
                    "word_embedding_dimension": EMBEDDING_DIMENSION,
                    "pooling_mode_cls_token": True,
                    "pooling_mode_mean_tokens": False,
                    "pooling_mode_max_tokens": False,
                    "pooling_mode_mean_sqrt_len_tokens": False,
                }
            ),
            encoding="utf-8",
        )

    def test_import_does_not_initialize_the_model(self):
        constructor_calls = []
        fake_qdrant = types.ModuleType("qdrant_client")
        fake_qdrant.QdrantClient = object
        fake_qdrant.models = FakeQdrantModels
        fake_sentence_transformers = types.ModuleType("sentence_transformers")
        fake_sentence_transformers.SentenceTransformer = (
            lambda *args, **kwargs: constructor_calls.append((args, kwargs))
        )

        sys.modules.pop("acc_statements.index", None)
        with patch.dict(
            sys.modules,
            {
                "qdrant_client": fake_qdrant,
                "sentence_transformers": fake_sentence_transformers,
            },
        ):
            importlib.import_module("acc_statements.index")

        self.assertEqual(constructor_calls, [])

    def test_embedding_configuration_keeps_identity_dimension_and_resolves_path(self):
        config = importlib.import_module("acc_statements.config")
        configured_path = Path(tempfile.gettempdir()) / "local-bge-model"
        original_value = os.environ.get("EMBED_MODEL_PATH")
        try:
            os.environ.pop("EMBED_MODEL_PATH", None)
            importlib.reload(config)
            self.assertEqual(config.EMBED_MODEL, "BAAI/bge-m3")
            self.assertEqual(config.EMBED_DIM, EMBEDDING_DIMENSION)
            self.assertIsNone(config.EMBED_MODEL_PATH)

            with patch.dict(
                os.environ,
                {"EMBED_MODEL_PATH": str(configured_path)},
            ):
                importlib.reload(config)
                self.assertEqual(config.EMBED_MODEL, "BAAI/bge-m3")
                self.assertEqual(config.EMBED_DIM, EMBEDDING_DIMENSION)
                self.assertEqual(
                    config.EMBED_MODEL_PATH,
                    configured_path.resolve(),
                )
        finally:
            if original_value is None:
                os.environ.pop("EMBED_MODEL_PATH", None)
            else:
                os.environ["EMBED_MODEL_PATH"] = original_value
            importlib.reload(config)

    def test_unset_local_path_preserves_model_id_loading(self):
        index = self.statement_index()
        fake_model = object()
        with (
            patch.object(index, "_embedder", None),
            patch.object(index.config, "EMBED_MODEL_PATH", None),
            patch.object(
                index,
                "SentenceTransformer",
                return_value=fake_model,
            ) as constructor,
        ):
            self.assertIs(index.get_embedder(), fake_model)

        constructor.assert_called_once_with("BAAI/bge-m3", device="cpu")

    def test_valid_local_path_is_resolved_and_loaded_on_cpu_once(self):
        index = self.statement_index()
        fake_models, calls = self.fake_model_modules()

        class FakeSentenceTransformer:
            def __init__(self, modules, device):
                calls["sentence_transformer"].append((modules, device))
                self.modules = modules
                self.device = device

        with tempfile.TemporaryDirectory() as temporary_directory:
            model_path = Path(temporary_directory) / "model"
            model_path.mkdir()
            self.create_local_model(model_path)
            configured_path = model_path / ".." / "model"

            with (
                patch.object(index, "_embedder", None),
                patch.object(index.config, "EMBED_MODEL_PATH", configured_path),
                patch.object(index, "SentenceTransformer", FakeSentenceTransformer),
                patch.dict(
                    sys.modules,
                    {"sentence_transformers.models": fake_models},
                ),
            ):
                first = index.get_embedder()
                second = index.get_embedder()

            self.assertIs(first, second)
            self.assertEqual(
                calls["transformer"],
                [
                    (
                        str(model_path.resolve()),
                        {
                            "max_seq_length": 8192,
                            "do_lower_case": False,
                            "model_args": {
                                "low_cpu_mem_usage": True,
                                "device_map": "cpu",
                            },
                        },
                    )
                ],
            )
            self.assertEqual(
                calls["pooling"],
                [
                    (
                        str(model_path / "1_Pooling"),
                        json.loads(
                            (model_path / "1_Pooling" / "config.json").read_text(
                                encoding="utf-8"
                            )
                        ),
                    )
                ],
            )
            self.assertEqual(
                calls["normalize"],
                [str(model_path / "2_Normalize")],
            )
            modules, device = calls["sentence_transformer"][0]
            self.assertEqual(
                [module.__class__.__name__ for module in modules],
                [
                    "FakeTransformer",
                    "FakePoolingInstance",
                    "FakeNormalizeInstance",
                ],
            )
            self.assertEqual(modules[1].pooling_config["pooling_mode_cls_token"], True)
            self.assertEqual(device, "cpu")

    def test_missing_local_directory_fails_before_model_construction(self):
        index = self.statement_index()
        with tempfile.TemporaryDirectory() as temporary_directory:
            missing_path = Path(temporary_directory) / "missing-model"
            with (
                patch.object(index, "_embedder", None),
                patch.object(index.config, "EMBED_MODEL_PATH", missing_path),
                patch.object(index, "SentenceTransformer") as constructor,
                self.assertRaisesRegex(FileNotFoundError, "EMBED_MODEL_PATH"),
            ):
                index.get_embedder()
            constructor.assert_not_called()

    def test_missing_or_invalid_local_configuration_fails_closed(self):
        index = self.statement_index()
        fake_models, _ = self.fake_model_modules()
        for config_value in (
            None,
            {"max_seq_length": "long", "do_lower_case": False},
        ):
            with self.subTest(config_value=config_value):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    model_path = Path(temporary_directory) / "model"
                    model_path.mkdir()
                    self.create_local_model(model_path)
                    config_path = model_path / "sentence_bert_config.json"
                    if config_value is None:
                        config_path.unlink()
                    else:
                        config_path.write_text(
                            json.dumps(config_value),
                            encoding="utf-8",
                        )
                    with (
                        patch.object(index, "_embedder", None),
                        patch.object(index.config, "EMBED_MODEL_PATH", model_path),
                        patch.object(index, "SentenceTransformer") as constructor,
                        patch.dict(
                            sys.modules,
                            {"sentence_transformers.models": fake_models},
                        ),
                        self.assertRaises(ValueError),
                    ):
                        index.get_embedder()
                    constructor.assert_not_called()

    def test_pooling_dimension_mismatch_fails_before_sentence_transformer(self):
        index = self.statement_index()
        fake_models, _ = self.fake_model_modules()
        with tempfile.TemporaryDirectory() as temporary_directory:
            model_path = Path(temporary_directory) / "model"
            model_path.mkdir()
            self.create_local_model(model_path)
            pooling_config_path = model_path / "1_Pooling" / "config.json"
            pooling_config = json.loads(
                pooling_config_path.read_text(encoding="utf-8")
            )
            pooling_config["word_embedding_dimension"] = 768
            pooling_config_path.write_text(
                json.dumps(pooling_config),
                encoding="utf-8",
            )
            with (
                patch.object(index, "_embedder", None),
                patch.object(index.config, "EMBED_MODEL_PATH", model_path),
                patch.object(index, "SentenceTransformer") as constructor,
                patch.dict(
                    sys.modules,
                    {"sentence_transformers.models": fake_models},
                ),
                self.assertRaisesRegex(ValueError, "Pooling output dimension"),
            ):
                index.get_embedder()
            constructor.assert_not_called()

    def test_local_model_requires_normalize_module(self):
        index = self.statement_index()
        with tempfile.TemporaryDirectory() as temporary_directory:
            model_path = Path(temporary_directory) / "model"
            model_path.mkdir()
            self.create_local_model(model_path)
            modules_path = model_path / "modules.json"
            modules = json.loads(modules_path.read_text(encoding="utf-8"))[:-1]
            modules_path.write_text(json.dumps(modules), encoding="utf-8")
            with (
                patch.object(index, "_embedder", None),
                patch.object(index.config, "EMBED_MODEL_PATH", model_path),
                patch.object(index, "SentenceTransformer") as constructor,
                self.assertRaisesRegex(ValueError, "Transformer, Pooling, and Normalize"),
            ):
                index.get_embedder()
            constructor.assert_not_called()

    def test_accelerate_requirement_is_pinned_once(self):
        requirements_path = Path(__file__).resolve().parents[1] / "requirements.txt"
        requirements = requirements_path.read_text(encoding="utf-8")
        self.assertEqual(
            sum(line.strip() == "accelerate==1.12.0" for line in requirements.splitlines()),
            1,
        )

    def test_incomplete_local_model_fails_before_model_construction(self):
        index = self.statement_index()
        with tempfile.TemporaryDirectory() as temporary_directory:
            model_path = Path(temporary_directory) / "incomplete-model"
            model_path.mkdir()
            (model_path / "modules.json").write_text("[]", encoding="utf-8")
            with (
                patch.object(index, "_embedder", None),
                patch.object(index.config, "EMBED_MODEL_PATH", model_path),
                patch.object(index, "SentenceTransformer") as constructor,
                self.assertRaisesRegex(
                    ValueError,
                    "Transformer, Pooling, and Normalize",
                ),
            ):
                index.get_embedder()
            constructor.assert_not_called()

    def test_invalid_local_path_never_falls_back_to_model_identifier(self):
        index = self.statement_index()
        with tempfile.TemporaryDirectory() as temporary_directory:
            model_path = Path(temporary_directory) / "invalid-model"
            model_path.mkdir()
            self.create_local_model(model_path)
            (model_path / "tokenizer.json").unlink()
            with (
                patch.object(index, "_embedder", None),
                patch.object(index.config, "EMBED_MODEL_PATH", model_path),
                patch.object(index, "SentenceTransformer") as constructor,
                self.assertRaisesRegex(ValueError, "tokenizer assets"),
            ):
                index.get_embedder()
            constructor.assert_not_called()

    def test_statement_search_excludes_ocr_points_by_default(self):
        index = self.statement_index()

        client = types.SimpleNamespace(
            query_points=lambda *args, **kwargs: (
                setattr(client, "query_filter", kwargs["query_filter"])
                or types.SimpleNamespace(points=[])
            )
        )
        with (
            patch.object(index, "get_client", return_value=client),
            patch.object(index, "embed", return_value=[[0.0] * EMBEDDING_DIMENSION]),
        ):
            self.assertEqual(index.search("statement query"), [])

        self.assertEqual(
            client.query_filter.must_not[0].key,
            "source_type",
        )
        self.assertEqual(
            client.query_filter.must_not[0].match.value,
            "ocr_document",
        )


if __name__ == "__main__":
    unittest.main()
