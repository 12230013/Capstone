import sys
import types
import unittest
from unittest.mock import patch

from app.database import ocr_storage


class FakeCollection:
    def __init__(self):
        self.records = {}

    def find_one(self, query):
        return self.records.get(query["_id"])

    def insert_one(self, document):
        self.records[document["_id"]] = dict(document)

    def update_one(self, query, update):
        record = self.records.get(query["_id"])
        if record is None or record.get("owner_user_id") != query.get("owner_user_id"):
            return types.SimpleNamespace(matched_count=0)
        record.update(update["$set"])
        return types.SimpleNamespace(matched_count=1)


class FakeDatabase:
    def __init__(self):
        self.files = FakeCollection()

    def __getitem__(self, collection_name):
        if collection_name == "ocr_document_files.files":
            return self.files
        raise AssertionError(f"Unexpected collection: {collection_name}")


class FakeGridFSFileExists(Exception):
    pass


class FakeGridFSBucket:
    def __init__(self, database, bucket_name):
        self.database = database
        self.bucket_name = bucket_name

    def upload_from_stream_with_id(
        self,
        file_id,
        filename,
        source,
        *,
        metadata,
    ):
        self.database.files.records[file_id] = {
            "_id": file_id,
            "filename": filename,
            "metadata": metadata,
            "content": source.read(),
        }


class OCRStorageTests(unittest.TestCase):
    def setUp(self):
        self.database = FakeDatabase()
        self.collection = FakeCollection()
        fake_gridfs = types.ModuleType("gridfs")
        fake_gridfs.__path__ = []
        fake_gridfs.GridFSBucket = FakeGridFSBucket
        fake_gridfs_errors = types.ModuleType("gridfs.errors")
        fake_gridfs_errors.FileExists = FakeGridFSFileExists
        self.patches = [
            patch.object(ocr_storage, "db", self.database),
            patch.object(
                ocr_storage,
                "ocr_documents_collection",
                self.collection,
            ),
            patch.dict(
                sys.modules,
                {
                    "gridfs": fake_gridfs,
                    "gridfs.errors": fake_gridfs_errors,
                },
            ),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def test_persists_source_document_status_and_page_result(self):
        import hashlib

        content = b"synthetic OCR document"
        document_id = hashlib.sha256(content).hexdigest()
        status = {
            "document_id": document_id,
            "owner_user_id": "local-test-user",
            "filename": "synthetic.pdf",
            "mime_type": "application/pdf",
            "status": "queued",
            "ocr_status": None,
            "index_status": "not_indexed",
        }

        ocr_storage.persist_ocr_document(status, content)
        result = {
            "document_id": document_id,
            "extraction_method": "paddleocr",
            "page_count": 1,
            "pages": [
                {
                    "page_number": 1,
                    "text": "Synthetic text",
                    "confidence": 91.2,
                }
            ],
        }
        ocr_storage.update_ocr_document(
            document_id,
            {
                "status": "completed",
                "extraction_method": "paddleocr",
                "page_count": 1,
            },
            owner_user_id="local-test-user",
            ocr_result=result,
        )

        stored = self.collection.records[document_id]
        self.assertEqual(stored["status"], "completed")
        self.assertEqual(stored["source_storage"], "gridfs")
        self.assertEqual(
            self.database.files.records[document_id]["content"],
            content,
        )
        self.assertEqual(stored["ocr_result"]["pages"][0]["page_number"], 1)
        self.assertEqual(stored["ocr_result"]["pages"][0]["confidence"], 91.2)

    def test_does_not_reassign_existing_document_to_another_owner(self):
        import hashlib

        content = b"synthetic OCR document"
        document_id = hashlib.sha256(content).hexdigest()
        status = {
            "document_id": document_id,
            "owner_user_id": "first-owner",
            "filename": "synthetic.pdf",
            "mime_type": "application/pdf",
            "status": "queued",
        }
        ocr_storage.persist_ocr_document(status, content)

        status["owner_user_id"] = "different-owner"
        with self.assertRaises(ocr_storage.OCRDocumentConflictError):
            ocr_storage.persist_ocr_document(
                status,
                content,
                allow_retry=True,
            )

        self.assertEqual(
            self.collection.records[document_id]["owner_user_id"],
            "first-owner",
        )

    def test_owner_scoped_document_id_keeps_content_hash_for_integrity(self):
        import hashlib

        content = b"same synthetic content for different owners"
        content_sha256 = hashlib.sha256(content).hexdigest()
        document_id = hashlib.sha256(
            f"acc-ocr-document\0second-owner\0{content_sha256}".encode("utf-8")
        ).hexdigest()
        status = {
            "document_id": document_id,
            "content_sha256": content_sha256,
            "owner_user_id": "second-owner",
            "filename": "synthetic.pdf",
            "mime_type": "application/pdf",
            "status": "queued",
        }

        ocr_storage.persist_ocr_document(status, content)

        self.assertEqual(
            self.collection.records[document_id]["content_sha256"],
            content_sha256,
        )
        self.assertEqual(
            self.database.files.records[document_id]["metadata"]["content_sha256"],
            content_sha256,
        )
        self.assertEqual(
            self.collection.records[document_id]["owner_user_id"],
            "second-owner",
        )

    def test_updates_require_matching_owner(self):
        import hashlib

        content = b"owner-scoped update"
        document_id = hashlib.sha256(content).hexdigest()
        status = {
            "document_id": document_id,
            "owner_user_id": "first-owner",
            "filename": "synthetic.pdf",
            "mime_type": "application/pdf",
            "status": "queued",
        }
        ocr_storage.persist_ocr_document(status, content)

        with self.assertRaises(TypeError):
            ocr_storage.update_ocr_document(
                document_id,
                {"status": "completed"},
            )
        with self.assertRaises(RuntimeError):
            ocr_storage.update_ocr_document(
                document_id,
                {"status": "completed"},
                owner_user_id="different-owner",
            )

        self.assertEqual(
            self.collection.records[document_id]["status"],
            "queued",
        )

    def test_retry_accepts_concurrent_gridfs_write_with_matching_hash(self):
        import hashlib

        content = b"synthetic OCR document"
        document_id = hashlib.sha256(content).hexdigest()
        status = {
            "document_id": document_id,
            "owner_user_id": "local-test-user",
            "filename": "synthetic.pdf",
            "mime_type": "application/pdf",
            "status": "queued",
        }
        ocr_storage.persist_ocr_document(status, content)
        del self.database.files.records[document_id]

        class RacingGridFSBucket(FakeGridFSBucket):
            def upload_from_stream_with_id(
                self,
                file_id,
                filename,
                source,
                *,
                metadata,
            ):
                self.database.files.records[file_id] = {
                    "_id": file_id,
                    "filename": filename,
                    "metadata": metadata,
                    "content": source.read(),
                }
                raise FakeGridFSFileExists("A concurrent request won the upload.")

        with patch.object(
            sys.modules["gridfs"],
            "GridFSBucket",
            RacingGridFSBucket,
        ):
            ocr_storage.persist_ocr_document(
                status,
                content,
                allow_retry=True,
            )

        self.assertEqual(
            self.database.files.records[document_id]["metadata"]["content_sha256"],
            document_id,
        )
        self.assertEqual(
            self.database.files.records[document_id]["content"],
            content,
        )

    def test_retry_rejects_concurrent_gridfs_write_with_different_hash(self):
        import hashlib

        content = b"synthetic OCR document"
        document_id = hashlib.sha256(content).hexdigest()
        status = {
            "document_id": document_id,
            "owner_user_id": "local-test-user",
            "filename": "synthetic.pdf",
            "mime_type": "application/pdf",
            "status": "queued",
        }
        ocr_storage.persist_ocr_document(status, content)
        del self.database.files.records[document_id]

        class RacingGridFSBucket(FakeGridFSBucket):
            def upload_from_stream_with_id(
                self,
                file_id,
                filename,
                source,
                *,
                metadata,
            ):
                self.database.files.records[file_id] = {
                    "_id": file_id,
                    "filename": filename,
                    "metadata": {"content_sha256": "different-content"},
                    "content": source.read(),
                }
                raise FakeGridFSFileExists("A conflicting file already exists.")

        with (
            patch.object(
                sys.modules["gridfs"],
                "GridFSBucket",
                RacingGridFSBucket,
            ),
            self.assertRaises(ocr_storage.OCRDocumentConflictError),
        ):
            ocr_storage.persist_ocr_document(
                status,
                content,
                allow_retry=True,
            )

    def test_rejects_content_that_does_not_match_document_id(self):
        status = {
            "document_id": "0" * 64,
            "owner_user_id": "local-test-user",
            "filename": "synthetic.pdf",
            "mime_type": "application/pdf",
            "status": "queued",
        }
        with self.assertRaises(ValueError):
            ocr_storage.persist_ocr_document(status, b"different content")

        self.assertEqual(self.collection.records, {})
