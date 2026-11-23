import ast
import hashlib
import importlib.util
import io
import json
import re
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class FakeObjectId(str):
    def __new__(cls, value=None):
        if value is None:
            import uuid

            value = uuid.uuid4().hex[:24]
        if not cls.is_valid(value):
            raise ValueError("Invalid ObjectId")
        return super().__new__(cls, value.lower())

    @staticmethod
    def is_valid(value):
        return isinstance(value, str) and re.fullmatch(
            r"[a-fA-F0-9]{24}",
            value,
        ) is not None


class FakeDatabase:
    def __getitem__(self, _collection_name):
        return None


class FakeMongoClient:
    def __getitem__(self, _database_name):
        return FakeDatabase()


bson_stub = types.ModuleType("bson")
bson_stub.ObjectId = FakeObjectId
pymongo_stub = types.ModuleType("pymongo")
pymongo_stub.MongoClient = FakeMongoClient
dotenv_stub = types.ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
dotenv_stub.dotenv_values = lambda *_args, **_kwargs: {}
sys.modules.update(
    {
        "bson": bson_stub,
        "pymongo": pymongo_stub,
        "dotenv": dotenv_stub,
    }
)

if importlib.util.find_spec("cv2") is None:
    cv2_stub = types.ModuleType("cv2")
    cv2_stub.error = Exception
    sys.modules["cv2"] = cv2_stub

import fitz
import httpx
from fastapi import FastAPI
from PIL import Image

from app.api.routes import ocr_documents
from app.routes import auth
from app.ocr import document_ocr
from app.utils import sessions
from app.utils.security import hash_password


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def make_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "\n".join(
            [
                "SYNTHETIC DEVELOPMENT TEST DOCUMENT",
                "This artificial page contains enough selectable text for direct extraction.",
                "It contains no real investigation data and is used only by automated tests.",
                "Page-level output must remain available for the local OCR API response.",
                "The document is intentionally synthetic and does not require OCR inference.",
            ]
        ),
    )
    contents = document.tobytes()
    document.close()
    return contents


def make_png() -> bytes:
    image = Image.new("RGB", (20, 20), color="white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    image.close()
    return output.getvalue()


def completed_result(document_id: str, filename: str) -> dict:
    return {
        "document_id": document_id,
        "layout_version": ocr_documents.LAYOUT_VERSION,
        "ocr_engine": ocr_documents.config.OCR_ENGINE,
        "ocr_model": ocr_documents.config.OCR_MODEL_ID,
        "filename": filename,
        "document_type": "pdf",
        "ocr_status": "completed",
        "extraction_method": "paddleocr",
        "page_count": 1,
        "pages": [
            {
                "page_number": 1,
                "text": "Synthetic page-level text.",
                "confidence": 92.1,
                "extraction_method": "paddleocr",
                "quality_decision": "manual_review_recommended",
            }
        ],
    }


class OCRDocumentAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temporary_directory.name)
        self.results_dir = self.data_root / "ocr"
        self.documents_dir = self.data_root / "documents"
        self.patches = [
            patch.object(ocr_documents.config, "APP_ENV", "development"),
            patch.object(ocr_documents.config, "OCR_RESULTS_DIR", self.results_dir),
            patch.object(ocr_documents.config, "DOCUMENTS_DIR", self.documents_dir),
            patch.object(ocr_documents.config, "OCR_MAX_UPLOAD_BYTES", 2 * 1024 * 1024),
            patch.object(document_ocr, "OCR_RESULTS_DIR", self.results_dir),
        ]
        for item in self.patches:
            item.start()

        self.app = FastAPI()
        self.app.include_router(ocr_documents.router)
        self.owner_id = "0123456789abcdef01234567"
        self.other_owner_id = "fedcba9876543210fedcba98"
        self.session = {
            "user_id": self.owner_id,
            "user": {"id": self.owner_id},
        }
        self.app.dependency_overrides[ocr_documents.require_session] = (
            lambda: self.session
        )
        self.mongo_documents = {}

        def persist_document(status, content, *, allow_retry=False):
            existing = self.mongo_documents.get(status["document_id"])
            if existing is not None and (
                not allow_retry
                or existing["owner_user_id"] != status["owner_user_id"]
            ):
                raise ocr_documents.OCRDocumentConflictError
            record = {
                **status,
                "document_id": status["document_id"],
                "content_sha256": status.get(
                    "content_sha256",
                    status["document_id"],
                ),
                "source_document": content,
                "ocr_result": (
                    existing.get("ocr_result") if existing is not None else None
                ),
            }
            self.mongo_documents[status["document_id"]] = record

        def update_document(
            document_id,
            updates,
            *,
            owner_user_id,
            ocr_result=None,
        ):
            record = self.mongo_documents[document_id]
            if record["owner_user_id"] != owner_user_id:
                raise RuntimeError("The OCR document owner could not be verified.")
            record.update(updates)
            if ocr_result is not None:
                record["ocr_result"] = ocr_result

        self.storage_patches = [
            patch.object(
                ocr_documents,
                "persist_ocr_document",
                side_effect=persist_document,
            ),
            patch.object(
                ocr_documents,
                "update_ocr_document",
                side_effect=update_document,
            ),
        ]
        for item in self.storage_patches:
            item.start()

        self.transport = httpx.ASGITransport(
            app=self.app,
            client=("127.0.0.1", 43210),
        )
        self.client = httpx.AsyncClient(
            transport=self.transport,
            base_url="http://localhost",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        for item in reversed(self.storage_patches):
            item.stop()
        for item in reversed(self.patches):
            item.stop()
        self.temporary_directory.cleanup()

    async def upload(self, filename: str, data: bytes, mime_type: str):
        return await self.client.post(
            "/api/ocr/documents",
            files={"file": (filename, data, mime_type)},
        )

    def mock_pipeline(self):
        def process(path, document_id, filename, mime_type, correlation_id):
            result = completed_result(document_id, filename)
            result["document_type"] = (
                "pdf" if mime_type == "application/pdf" else "image"
            )
            result["correlation_id"] = correlation_id
            return result

        return patch.object(ocr_documents, "run_document_ocr", side_effect=process)

    async def test_ocr_mutations_use_real_session_cookie_csrf_and_origin_checks(self):
        token = "synthetic-session-token"
        csrf_token = "synthetic-csrf-token"
        now = datetime.now(timezone.utc)
        session_document = {
            "_id": FakeObjectId(),
            "token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "csrf_token": csrf_token,
            "user_id": self.owner_id,
            "expires_at": now + timedelta(hours=1),
            "last_seen_at": now,
            "ended_at": None,
        }
        user = {
            "_id": FakeObjectId(self.owner_id),
            "name": "Synthetic Test User",
            "employee_id": "ACC-TEST-1",
            "email": "synthetic@example.com",
            "role": "Investigator",
            "department": "Investigations",
        }
        sessions_collection = Mock()
        sessions_collection.find_one.return_value = session_document
        sessions_collection.update_one.return_value = SimpleNamespace(
            matched_count=1,
        )
        users_collection = Mock()
        users_collection.find_one.return_value = user
        self.app.dependency_overrides.pop(ocr_documents.require_session)
        self.client.cookies.set("acc_session", token)
        with (
            patch.object(sessions, "sessions_collection", sessions_collection),
            patch.object(sessions, "users_collection", users_collection),
            patch.object(
                sessions.settings,
                "frontend_origins",
                "http://localhost:5173",
            ),
        ):
            missing_csrf = await self.client.post(
                "/api/ocr/documents",
                headers={"Origin": "http://localhost:5173"},
            )
            bad_origin = await self.client.post(
                "/api/ocr/documents",
                headers={
                    "Origin": "https://attacker.example",
                    "X-CSRF-Token": csrf_token,
                },
            )
            invalid_csrf = await self.client.post(
                "/api/ocr/documents",
                headers={
                    "Origin": "http://localhost:5173",
                    "X-CSRF-Token": "incorrect-csrf-token",
                },
            )
        self.app.dependency_overrides[ocr_documents.require_session] = (
            lambda: self.session
        )
        self.assertEqual(missing_csrf.status_code, 403)
        self.assertEqual(bad_origin.status_code, 403)
        self.assertEqual(invalid_csrf.status_code, 403)
        self.assertEqual(self.mongo_documents, {})

    async def test_login_cookie_can_access_an_ocr_endpoint(self):
        document_id = await self.completed_document()
        self.app.include_router(auth.router)
        self.app.dependency_overrides.pop(ocr_documents.require_session)

        password_hash = hash_password("Password1!")
        user = {
            "_id": FakeObjectId(self.owner_id),
            "name": "Synthetic Test User",
            "employee_id": "ACC-TEST-1",
            "email": "synthetic@example.com",
            "role": "Investigator",
            "department": "Investigations",
            "password": password_hash,
        }
        created_session = {}

        def save_session(document):
            created_session.update(document)
            created_session["_id"] = FakeObjectId()

        users_collection = Mock()
        users_collection.find_one.return_value = user
        sessions_collection = Mock()
        sessions_collection.insert_one.side_effect = save_session
        sessions_collection.find_one.side_effect = (
            lambda _query: created_session or None
        )
        sessions_collection.update_one.return_value = SimpleNamespace(
            matched_count=1,
        )
        activity_collection = Mock()
        try:
            with (
                patch.object(auth, "users_collection", users_collection),
                patch.object(auth, "sessions_collection", sessions_collection),
                patch.object(auth, "activity_collection", activity_collection),
                patch.object(sessions, "users_collection", users_collection),
                patch.object(sessions, "sessions_collection", sessions_collection),
                patch.object(
                    sessions.settings,
                    "frontend_origins",
                    "http://localhost:5173",
                ),
            ):
                login = await self.client.post(
                    "/api/auth/login",
                    json={
                        "email": "synthetic@example.com",
                        "password": "Password1!",
                    },
                    headers={"Origin": "http://localhost:5173"},
                )
                status = await self.client.get(
                    f"/api/ocr/documents/{document_id}/status"
                )
        finally:
            self.app.dependency_overrides[ocr_documents.require_session] = (
                lambda: self.session
            )

        self.assertEqual(login.status_code, 200)
        self.assertIn("acc_session", self.client.cookies)
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["document_id"], document_id)

    async def completed_document(self, filename="indexed.pdf"):
        with self.mock_pipeline():
            response = await self.upload(filename, make_pdf(), "application/pdf")
        self.assertIn(response.status_code, {200, 202})
        return response.json()["document_id"]

    async def test_evaluation_uses_original_text_and_enforces_ownership(self):
        document_id = await self.completed_document()
        result_path = self.results_dir / f"{document_id}.json"
        result = json.loads(result_path.read_text())
        result["pages"][0]["extracted_text"] = "Original text."
        result["pages"][0]["text"] = "Review edits."
        result["reviewed_at"] = "2026-11-23T00:00:00Z"
        result_path.write_text(json.dumps(result))
        payload = {"page_number": 1, "reference_text": "Original text."}
        evaluated = await self.client.post(f"/api/ocr/documents/{document_id}/evaluate", json=payload)
        self.assertEqual(evaluated.status_code, 200)
        self.assertEqual(evaluated.json()["cer_percent"], 0)
        self.assertEqual(json.loads(result_path.read_text())["pages"][0]["text"], "Review edits.")
        self.session["user_id"] = self.other_owner_id
        denied = await self.client.post(f"/api/ocr/documents/{document_id}/evaluate", json=payload)
        self.assertIn(denied.status_code, (403, 404))

    async def test_evaluation_requires_reference_and_valid_page(self):
        document_id = await self.completed_document()
        for payload, expected in [({"page_number": 99, "reference_text": "text"}, 404), ({"page_number": 1, "reference_text": " "}, 400), ({"page_number": 1, "reference_text": "x" * 20001}, 422)]:
            response = await self.client.post(f"/api/ocr/documents/{document_id}/evaluate", json=payload)
            self.assertEqual(response.status_code, expected)

    async def test_valid_pdf_runs_pipeline_and_preserves_page_metadata(self):
        pdf = make_pdf()
        with self.mock_pipeline() as process:
            response = await self.upload("synthetic.pdf", pdf, "application/pdf")

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "queued")
        document_id = response.json()["document_id"]
        process.assert_called_once()
        saved_path = self.documents_dir / f"{document_id}.pdf"
        self.assertEqual(saved_path.read_bytes(), pdf)
        mongo_document = self.mongo_documents[document_id]
        self.assertEqual(mongo_document["source_document"], pdf)
        self.assertEqual(mongo_document["status"], "completed")
        self.assertEqual(
            mongo_document["ocr_result"]["pages"][0]["page_number"],
            1,
        )
        self.assertEqual(
            mongo_document["ocr_result"]["pages"][0]["confidence"],
            92.1,
        )

        status = await self.client.get(
            f"/api/ocr/documents/{document_id}/status"
        )
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "completed")

        result = await self.client.get(f"/api/ocr/documents/{document_id}")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["pages"][0]["page_number"], 1)
        self.assertEqual(result.json()["pages"][0]["confidence"], 92.1)
        self.assertEqual(
            result.json()["pages"][0]["extraction_method"],
            "paddleocr",
        )

    async def test_digital_pdf_uses_real_pipeline_without_loading_ocr_model(self):
        with patch.object(ocr_documents, "_create_qdrant_adapter") as adapter_factory:
            response = await self.upload(
                "synthetic-direct.pdf",
                make_pdf(),
                "application/pdf",
            )
        document_id = response.json()["document_id"]
        result = await self.client.get(f"/api/ocr/documents/{document_id}")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["ocr_status"], "not_required")
        self.assertEqual(result.json()["extraction_method"], "direct")
        self.assertIn("SYNTHETIC DEVELOPMENT", result.json()["pages"][0]["text"])
        adapter_factory.assert_not_called()

    async def test_valid_png_runs_pipeline(self):
        with self.mock_pipeline() as process:
            response = await self.upload("synthetic.png", make_png(), "image/png")
        self.assertEqual(response.status_code, 202)
        status = await self.client.get(
            f"/api/ocr/documents/{response.json()['document_id']}/status"
        )
        self.assertEqual(status.json()["status"], "completed")
        process.assert_called_once()

    async def test_upload_filename_is_sanitized_before_storage_and_metadata(self):
        with self.mock_pipeline():
            response = await self.upload(
                "..\\..\\synthetic.pdf",
                make_pdf(),
                "application/pdf",
            )
        self.assertEqual(response.status_code, 202)
        document_id = response.json()["document_id"]
        status = await self.client.get(
            f"/api/ocr/documents/{document_id}/status"
        )
        self.assertEqual(status.json()["filename"], "synthetic.pdf")
        self.assertEqual(
            [path.name for path in self.documents_dir.iterdir()],
            [f"{document_id}.pdf"],
        )

    async def test_unsupported_extension_and_mime_mismatch_are_rejected(self):
        unsupported = await self.upload(
            "synthetic.txt",
            b"synthetic",
            "text/plain",
        )
        self.assertEqual(unsupported.status_code, 415)

        mismatch = await self.upload(
            "synthetic.jpg",
            make_png(),
            "image/jpeg",
        )
        self.assertEqual(mismatch.status_code, 415)

    async def test_invalid_pdf_and_empty_upload_are_rejected(self):
        invalid_pdf = await self.upload(
            "invalid.pdf",
            b"not a pdf",
            "application/pdf",
        )
        self.assertEqual(invalid_pdf.status_code, 415)

        empty_pdf = await self.upload("empty.pdf", b"", "application/pdf")
        self.assertEqual(empty_pdf.status_code, 400)

        malformed_pdf = await self.upload(
            "malformed.pdf",
            b"%PDF-1.7\nnot a valid PDF body",
            "application/pdf",
        )
        self.assertEqual(malformed_pdf.status_code, 400)

    async def test_oversized_upload_is_rejected_before_storage(self):
        with patch.object(ocr_documents.config, "OCR_MAX_UPLOAD_BYTES", 16):
            response = await self.upload(
                "large.pdf",
                b"x" * 17,
                "application/pdf",
            )
        self.assertEqual(response.status_code, 413)
        self.assertFalse(self.documents_dir.exists())

    async def test_processing_failure_is_persisted_without_internal_error_details(self):
        with patch.object(
            ocr_documents,
            "run_document_ocr",
            side_effect=RuntimeError("private engine detail"),
        ):
            response = await self.upload(
                "failure.pdf",
                make_pdf(),
                "application/pdf",
            )

        document_id = response.json()["document_id"]
        status = await self.client.get(
            f"/api/ocr/documents/{document_id}/status"
        )
        self.assertEqual(status.json()["status"], "failed")
        self.assertEqual(status.json()["error_code"], "processing_failed")
        result = await self.client.get(f"/api/ocr/documents/{document_id}")
        self.assertEqual(result.json()["error_code"], "processing_failed")
        self.assertNotIn("private engine detail", result.text)

    async def test_duplicate_upload_returns_existing_status_without_reprocessing(self):
        pdf = make_pdf()
        with self.mock_pipeline() as process:
            first = await self.upload("synthetic.pdf", pdf, "application/pdf")
            document_id = first.json()["document_id"]
            self.mongo_documents.pop(document_id)
            second = await self.upload("renamed.pdf", pdf, "application/pdf")

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["duplicate"])
        self.assertEqual(document_id, second.json()["document_id"])
        self.assertIn(document_id, self.mongo_documents)
        self.assertIsNotNone(self.mongo_documents[document_id]["ocr_result"])
        process.assert_called_once()

    async def test_different_ocr_model_reprocesses_unreviewed_duplicate(self):
        document_id = await self.completed_document()
        path = self.results_dir / f"{document_id}.json"
        result = json.loads(path.read_text())
        result["ocr_model"] = "PP-OCRv5-mobile"
        path.write_text(json.dumps(result))
        with self.mock_pipeline() as process:
            response = await self.upload("indexed.pdf", make_pdf(), "application/pdf")
        self.assertEqual(response.status_code, 202)
        process.assert_called_once()

    async def test_outdated_unreviewed_duplicate_is_reextracted(self):
        document_id=await self.completed_document()
        result_path=self.results_dir / f"{document_id}.json"
        previous=json.loads(result_path.read_text());previous.pop("layout_version",None)
        result_path.write_text(json.dumps(previous))
        with self.mock_pipeline() as process:
            response=await self.upload("indexed.pdf",(self.documents_dir / f"{document_id}.pdf").read_bytes(),"application/pdf")
        self.assertEqual(response.status_code,202)
        process.assert_called_once()
        self.assertEqual(self.mongo_documents[document_id]["ocr_result"]["layout_version"],ocr_documents.LAYOUT_VERSION)

    async def test_outdated_reviewed_duplicate_is_not_overwritten(self):
        document_id=await self.completed_document()
        result_path=self.results_dir / f"{document_id}.json"
        previous=json.loads(result_path.read_text());previous.pop("layout_version",None);previous["reviewed_at"]="2026-11-23T00:00:00Z"
        result_path.write_text(json.dumps(previous))
        with self.mock_pipeline() as process:
            response=await self.upload("indexed.pdf",(self.documents_dir / f"{document_id}.pdf").read_bytes(),"application/pdf")
        self.assertEqual(response.status_code,200)
        process.assert_not_called()

    async def test_identical_upload_by_another_user_gets_an_isolated_document(self):
        pdf = make_pdf()
        with self.mock_pipeline() as process:
            first = await self.upload("synthetic.pdf", pdf, "application/pdf")
            first_document_id = first.json()["document_id"]

            self.session["user_id"] = self.other_owner_id
            self.session["user"] = {"id": self.other_owner_id}
            second = await self.upload("synthetic.pdf", pdf, "application/pdf")
            second_document_id = second.json()["document_id"]
            repeated = await self.upload("renamed.pdf", pdf, "application/pdf")

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertNotEqual(first_document_id, second_document_id)
        self.assertEqual(second.json()["owner_user_id"], self.other_owner_id)
        self.assertEqual(repeated.status_code, 200)
        self.assertTrue(repeated.json()["duplicate"])
        self.assertEqual(repeated.json()["document_id"], second_document_id)
        self.assertEqual(
            self.mongo_documents[first_document_id]["owner_user_id"],
            self.owner_id,
        )
        self.assertEqual(
            self.mongo_documents[second_document_id]["owner_user_id"],
            self.other_owner_id,
        )
        self.assertEqual(process.call_count, 2)

    async def test_ocr_documents_are_not_visible_to_another_unassigned_user(self):
        with self.mock_pipeline():
            upload = await self.upload(
                "owned.pdf",
                make_pdf(),
                "application/pdf",
            )
        document_id = upload.json()["document_id"]
        self.session["user_id"] = self.other_owner_id
        self.session["user"] = {"id": self.other_owner_id}

        status = await self.client.get(
            f"/api/ocr/documents/{document_id}/status"
        )
        result = await self.client.get(f"/api/ocr/documents/{document_id}")

        self.assertEqual(status.status_code, 404)
        self.assertEqual(result.status_code, 404)

    async def test_ocr_upload_requires_a_validated_session(self):
        self.app.dependency_overrides.pop(ocr_documents.require_session)
        try:
            response = await self.upload(
                "synthetic.pdf",
                make_pdf(),
                "application/pdf",
            )
        finally:
            self.app.dependency_overrides[ocr_documents.require_session] = (
                lambda: self.session
            )
        self.assertEqual(response.status_code, 401)

    async def test_case_number_is_rejected_before_qdrant_indexing(self):
        document_id = await self.completed_document()
        adapter = SimpleNamespace(
            upsert_document=Mock(
                return_value={
                    "document_id": document_id,
                    "collection": "ocr_documents",
                    "chunks_upserted": 1,
                }
            )
        )
        with patch.object(
            ocr_documents,
            "_create_qdrant_adapter",
            return_value=adapter,
        ):
            response = await self.client.post(
                f"/api/ocr/documents/{document_id}/index",
                json={
                    "review_confirmed": True,
                    "case_no": "ACC/2026/014",
                },
            )

        self.assertEqual(response.status_code, 403)
        adapter.upsert_document.assert_not_called()
        self.assertNotIn("case_no", self.mongo_documents[document_id])

    async def test_reviewed_page_edits_are_saved_and_indexed_with_metadata(self):
        document_id = await self.completed_document()
        adapter = SimpleNamespace(
            upsert_document=Mock(
                return_value={
                    "document_id": document_id,
                    "collection": "ocr_documents",
                    "chunks_upserted": 1,
                }
            )
        )
        corrected_text = "Human-corrected synthetic page text."
        with patch.object(
            ocr_documents,
            "_create_qdrant_adapter",
            return_value=adapter,
        ):
            response = await self.client.post(
                f"/api/ocr/documents/{document_id}/index",
                json={
                    "review_confirmed": True,
                    "reviewed_pages": [
                        {"page_number": 1, "text": corrected_text},
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        indexed_result = adapter.upsert_document.call_args.args[0]
        self.assertEqual(indexed_result["pages"][0]["text"], corrected_text)
        self.assertEqual(indexed_result["pages"][0]["page_number"], 1)
        self.assertEqual(indexed_result["pages"][0]["confidence"], 92.1)
        self.assertEqual(
            indexed_result["pages"][0]["extraction_method"],
            "paddleocr",
        )
        self.assertEqual(
            self.mongo_documents[document_id]["ocr_result"]["pages"][0]["text"],
            corrected_text,
        )
        saved_result = self.results_dir / f"{document_id}.json"
        self.assertEqual(
            json.loads(saved_result.read_text(encoding="utf-8"))["pages"][0]["text"],
            corrected_text,
        )

    async def test_structured_review_is_saved_and_indexed_as_canonical_text(self):
        document_id = await self.completed_document()
        adapter = SimpleNamespace(upsert_document=Mock(return_value={"collection":"ocr_documents","chunks_upserted":1}))
        blocks = [{"type":"table","rows":[["Item","Amount"],["Travel","750"]]}, {"type":"form","fields":[{"label":"Approved by","value":"Reviewer"}]}]
        with patch.object(ocr_documents,"_create_qdrant_adapter",return_value=adapter):
            response = await self.client.post(f"/api/ocr/documents/{document_id}/index", json={"review_confirmed":True,"reviewed_pages":[{"page_number":1,"text":"stale plain text","blocks":blocks}]})
        self.assertEqual(response.status_code,200)
        page = adapter.upsert_document.call_args.args[0]["pages"][0]
        self.assertIn("Amount: 750",page["text"])
        self.assertIn("Approved by: Reviewer",page["text"])
        self.assertNotIn("stale plain text",page["text"])
        self.assertEqual(self.mongo_documents[document_id]["ocr_result"]["pages"][0]["blocks"],page["blocks"])

    async def test_ragged_review_table_is_rejected_before_indexing(self):
        document_id = await self.completed_document()
        with patch.object(ocr_documents,"_create_qdrant_adapter") as factory:
            response = await self.client.post(f"/api/ocr/documents/{document_id}/index", json={"review_confirmed":True,"reviewed_pages":[{"page_number":1,"text":"","blocks":[{"type":"table","rows":[["A","B"],["incomplete"]]}]}]})
        self.assertEqual(response.status_code,400)
        factory.assert_not_called()

    async def test_rich_review_is_authoritative_and_preserved_in_storage(self):
        document_id = await self.completed_document()
        rich = {"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"Reviewed rich document.","marks":[{"type":"bold"}]}]}]}
        adapter = SimpleNamespace(upsert_document=Mock(return_value={"collection":"ocr_documents","chunks_upserted":1}))
        with patch.object(ocr_documents,"_create_qdrant_adapter",return_value=adapter):
            response = await self.client.post(f"/api/ocr/documents/{document_id}/index",json={"review_confirmed":True,"reviewed_pages":[{"page_number":1,"text":"stale text","editor_json":rich}]})
        self.assertEqual(response.status_code,200)
        page=adapter.upsert_document.call_args.args[0]["pages"][0]
        self.assertEqual(page["text"],"Reviewed rich document.")
        self.assertEqual(self.mongo_documents[document_id]["ocr_result"]["pages"][0]["editor_json"],rich)

    async def test_reextract_uses_retained_original_and_requires_review_again(self):
        document_id = await self.completed_document()
        with self.mock_pipeline() as process:
            response=await self.client.post(f"/api/ocr/documents/{document_id}/reprocess")
        self.assertEqual(response.status_code,202)
        process.assert_called_once()
        self.assertEqual(self.mongo_documents[document_id]["index_status"],"not_indexed")
        with patch.object(ocr_documents,"_session_owner_id",return_value="other-owner"):
            denied=await self.client.post(f"/api/ocr/documents/{document_id}/reprocess")
        self.assertEqual(denied.status_code,404)

    async def test_case_number_metadata_is_saved_without_case_authorization_link(self):
        document_id = await self.completed_document()
        adapter = SimpleNamespace(upsert_document=Mock(return_value={"collection":"ocr_documents","chunks_upserted":1}))
        with patch.object(ocr_documents,"_create_qdrant_adapter",return_value=adapter):
            response = await self.client.post(f"/api/ocr/documents/{document_id}/index",json={"review_confirmed":True,"case_number":"  TEST-001  ","reviewed_pages":[{"page_number":1,"text":"Reviewed evidence."}]})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["case_number"],"TEST-001")
        self.assertIsNone(adapter.upsert_document.call_args.kwargs["case_no"])
        self.assertEqual(adapter.upsert_document.call_args.args[0]["case_number"],"TEST-001")
        self.assertEqual(self.mongo_documents[document_id]["ocr_result"]["case_number"],"TEST-001")
        self.assertEqual(self.mongo_documents[document_id]["case_number"],"TEST-001")

    async def test_reviewed_page_numbers_must_match_ocr_result(self):
        document_id = await self.completed_document()
        with patch.object(ocr_documents, "_create_qdrant_adapter") as factory:
            response = await self.client.post(
                f"/api/ocr/documents/{document_id}/index",
                json={
                    "review_confirmed": True,
                    "reviewed_pages": [
                        {"page_number": 2, "text": "Unrelated page text."},
                    ],
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("page numbers exactly", response.text)
        factory.assert_not_called()
        self.assertEqual(
            self.mongo_documents[document_id]["ocr_result"]["pages"][0]["text"],
            "Synthetic page-level text.",
        )

    async def test_owner_can_index_reviewed_document_without_a_case_grant(self):
        document_id = await self.completed_document()
        adapter = SimpleNamespace(
            upsert_document=Mock(
                return_value={
                    "document_id": document_id,
                    "collection": "ocr_documents",
                    "chunks_upserted": 1,
                }
            )
        )
        with patch.object(
            ocr_documents,
            "_create_qdrant_adapter",
            return_value=adapter,
        ):
            response = await self.client.post(
                f"/api/ocr/documents/{document_id}/index",
                json={"review_confirmed": True},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["collection"], "ocr_documents")
        adapter.upsert_document.assert_called_once()
        self.assertIsNone(adapter.upsert_document.call_args.kwargs["case_no"])

    async def test_non_loopback_ocr_request_is_blocked(self):
        document_id = await self.completed_document()
        remote_transport = httpx.ASGITransport(
            app=self.app,
            client=("203.0.113.12", 43210),
        )
        with patch.object(ocr_documents, "_create_qdrant_adapter") as factory:
            async with httpx.AsyncClient(
                transport=remote_transport,
                base_url="http://localhost",
            ) as remote_client:
                response = await remote_client.post(
                    f"/api/ocr/documents/{document_id}/index",
                    json={"review_confirmed": True},
                )
        self.assertEqual(response.status_code, 404)
        factory.assert_not_called()

    async def test_non_owner_cannot_index_another_users_document(self):
        document_id = await self.completed_document()
        self.session["user_id"] = self.other_owner_id
        self.session["user"] = {"id": self.other_owner_id}
        with patch.object(ocr_documents, "_create_qdrant_adapter") as factory:
            response = await self.client.post(
                f"/api/ocr/documents/{document_id}/index",
                json={"review_confirmed": True},
            )
        self.assertEqual(response.status_code, 404)
        factory.assert_not_called()

    async def test_indexing_requires_explicit_true_review_confirmation(self):
        document_id = await self.completed_document()
        missing = await self.client.post(
            f"/api/ocr/documents/{document_id}/index",
            json={},
        )
        false_value = await self.client.post(
            f"/api/ocr/documents/{document_id}/index",
            json={"review_confirmed": False},
        )
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(false_value.status_code, 400)

    async def test_indexing_requires_a_validated_session(self):
        document_id = await self.completed_document()
        self.app.dependency_overrides.pop(ocr_documents.require_session)
        try:
            response = await self.client.post(
                f"/api/ocr/documents/{document_id}/index",
                json={"review_confirmed": True},
            )
        finally:
            self.app.dependency_overrides[ocr_documents.require_session] = (
                lambda: self.session
            )
        self.assertEqual(response.status_code, 401)

    async def test_incomplete_ocr_processing_cannot_be_indexed(self):
        document_id = await self.completed_document()
        incomplete_status = {
            "document_id": document_id,
            "owner_user_id": self.session["user_id"],
            "status": "processing",
            "index_status": "not_indexed",
        }
        with (
            patch.object(
                ocr_documents,
                "_read_status",
                return_value=incomplete_status,
            ),
            patch.object(ocr_documents, "_create_qdrant_adapter") as factory,
        ):
            response = await self.client.post(
                f"/api/ocr/documents/{document_id}/index",
                json={"review_confirmed": True},
            )
        self.assertEqual(response.status_code, 409)
        factory.assert_not_called()

    async def test_indexing_requires_review_and_reports_adapter_failure(self):
        with self.mock_pipeline():
            upload = await self.upload(
                "index-failure.pdf",
                make_pdf(),
                "application/pdf",
            )
        document_id = upload.json()["document_id"]
        rejected = await self.client.post(
            f"/api/ocr/documents/{document_id}/index",
            json={
                "review_confirmed": False,
                "case_no": "ACC/2026/014",
            },
        )
        self.assertEqual(rejected.status_code, 400)

        with patch.object(
            ocr_documents,
            "_create_qdrant_adapter",
            side_effect=RuntimeError("private qdrant detail"),
        ):
            failed = await self.client.post(
                f"/api/ocr/documents/{document_id}/index",
                json={
                    "review_confirmed": True,
                },
            )
        self.assertEqual(failed.status_code, 503)
        self.assertNotIn("private qdrant detail", failed.text)
        status = await self.client.get(
            f"/api/ocr/documents/{document_id}/status"
        )
        self.assertEqual(status.json()["index_status"], "index_failed")

    async def test_router_is_disabled_outside_development_and_remote_clients_are_blocked(self):
        with patch.object(ocr_documents.config, "APP_ENV", "production"):
            disabled = await self.client.get(
                f"/api/ocr/documents/{'a' * 64}/status"
            )
        self.assertEqual(disabled.status_code, 404)

        remote_transport = httpx.ASGITransport(
            app=self.app,
            client=("203.0.113.12", 43210),
        )
        async with httpx.AsyncClient(
            transport=remote_transport,
            base_url="http://localhost",
        ) as remote_client:
            remote = await remote_client.get(
                f"/api/ocr/documents/{'a' * 64}/status"
            )
        self.assertEqual(remote.status_code, 404)


class LocalhostPolicyTests(unittest.TestCase):
    def test_only_loopback_ip_addresses_are_accepted(self):
        self.assertTrue(ocr_documents._is_loopback_host("127.0.0.1"))
        self.assertTrue(ocr_documents._is_loopback_host("::1"))
        self.assertTrue(ocr_documents._is_loopback_host("::ffff:127.0.0.1"))
        self.assertFalse(ocr_documents._is_loopback_host("203.0.113.12"))
        self.assertFalse(ocr_documents._is_loopback_host("localhost"))
        self.assertFalse(ocr_documents._is_loopback_host(None))

    def test_main_registers_the_ocr_router(self):
        main_path = BACKEND_ROOT / "app" / "main.py"
        tree = ast.parse(main_path.read_text(encoding="utf-8"))
        imports_ocr_router = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "app.api.routes.ocr_documents"
            for node in ast.walk(tree)
        )
        includes_ocr_router = any(
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "include_router"
            and node.value.args
            and isinstance(node.value.args[0], ast.Name)
            and node.value.args[0].id == "ocr_documents_router"
            for node in ast.walk(tree)
        )
        self.assertTrue(imports_ocr_router)
        self.assertTrue(includes_ocr_router)


if __name__ == "__main__":
    unittest.main()
