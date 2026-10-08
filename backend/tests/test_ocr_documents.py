import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

os.environ.setdefault("CDR_API_BASE_URL", "http://127.0.0.1:9")
_database_directory = tempfile.TemporaryDirectory()
os.environ["OCR_DATABASE_URL"] = (
    f"sqlite:///{Path(_database_directory.name, 'test.sqlite3').as_posix()}"
)

import fitz
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import ocr_documents
from app.ocr import database, document_ocr

app = FastAPI(title="OCR route tests")
app.include_router(ocr_documents.router)


def tearDownModule():
    database.engine.dispose()
    _database_directory.cleanup()


class OCRDocumentRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.Base.metadata.create_all(bind=database.engine)

    def setUp(self):
        with database.SessionLocal() as session:
            session.query(database.UploadedDocument).delete()
            session.commit()
        self.storage = tempfile.TemporaryDirectory()
        self.ocr_storage = tempfile.TemporaryDirectory()
        ocr_documents.DOCUMENTS_DIR = self.storage.name
        document_ocr.OCR_RESULTS_DIR = self.ocr_storage.name
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.storage.cleanup()
        self.ocr_storage.cleanup()

    @staticmethod
    def make_pdf(text):
        document = fitz.open()
        page = document.new_page()
        if text:
            page.insert_textbox(fitz.Rect(50, 50, 550, 750), text, fontsize=12)
        content = document.tobytes()
        document.close()
        return content

    @staticmethod
    def make_scanned_pdf():
        image = np.full((500, 1400, 3), 255, dtype=np.uint8)
        cv2.putText(
            image,
            "SYNTHETIC OCR TEST 12345",
            (60, 270),
            cv2.FONT_HERSHEY_SIMPLEX,
            2.0,
            (0, 0, 0),
            4,
            cv2.LINE_AA,
        )
        image_buffer = io.BytesIO()
        Image.fromarray(image).save(image_buffer, format="PNG")
        document = fitz.open()
        page = document.new_page(width=1400, height=500)
        page.insert_image(page.rect, stream=image_buffer.getvalue())
        content = document.tobytes()
        document.close()
        return content

    def upload(self, filename, content):
        return self.client.post(
            "/documents/upload",
            files={"file": (filename, content)},
            data={"uploaded_by": "Test user"},
        )

    def test_upload_and_metadata_preserve_the_document(self):
        content = self.make_pdf("Synthetic test document")
        response = self.upload("synthetic.pdf", content)
        self.assertEqual(response.status_code, 201, response.text)
        metadata = response.json()
        self.assertRegex(metadata["document_id"], r"^DOC-\d{5,}$")
        self.assertEqual(metadata["file_type"], "application/pdf")
        self.assertEqual(
            Path(self.storage.name, "synthetic.pdf").read_bytes(),
            content,
        )
        self.assertEqual(
            self.client.get(f"/documents/{metadata['document_id']}").json(),
            metadata,
        )

    def test_upload_rejects_bad_extension_signature_traversal_and_duplicate(self):
        self.assertEqual(self.upload("sample.docx", b"not supported").status_code, 415)
        self.assertEqual(self.upload("fake.pdf", b"not a PDF").status_code, 400)
        self.assertEqual(self.upload(r"..\outside.pdf", b"%PDF-1.7").status_code, 400)
        self.assertEqual(self.upload("same.pdf", b"%PDF-1.7").status_code, 201)
        self.assertEqual(self.upload("same.pdf", b"%PDF-1.7").status_code, 409)

    def test_digital_pdf_detects_and_extracts_page_text_without_ocr(self):
        text = (
            "Synthetic digital PDF evidence document containing selectable text. "
            "This page has enough words to satisfy the detection threshold. "
        ) * 3
        upload = self.upload("digital.pdf", self.make_pdf(text))
        document_id = upload.json()["document_id"]
        detected = self.client.post(f"/documents/{document_id}/detect")
        self.assertEqual(detected.status_code, 200, detected.text)
        self.assertEqual(detected.json()["classification"], "digital_pdf")
        extracted = self.client.post(f"/documents/{document_id}/extract")
        self.assertEqual(extracted.status_code, 200, extracted.text)
        self.assertEqual(extracted.json()["extraction_method"], "direct")
        self.assertIn("Synthetic digital PDF", extracted.json()["pages"][0]["text"])

    def test_scanned_pdf_is_marked_ocr_required_and_not_directly_extracted(self):
        upload = self.upload("scanned.pdf", self.make_pdf(""))
        document_id = upload.json()["document_id"]
        detected = self.client.post(f"/documents/{document_id}/detect")
        self.assertEqual(detected.status_code, 200, detected.text)
        self.assertEqual(detected.json()["classification"], "scanned_pdf")
        extracted = self.client.post(f"/documents/{document_id}/extract")
        self.assertEqual(extracted.json()["extraction_method"], "ocr_required")
        self.assertTrue(extracted.json()["ocr_required"])

    def test_ocr_result_is_persisted(self):
        upload = self.upload("image.png", b"\x89PNG\r\n\x1a\nsynthetic")
        document_id = upload.json()["document_id"]
        result = {
            "document_id": document_id,
            "ocr_engine": "tesseract",
            "ocr_status": "completed",
            "pages": [{"page_number": 1, "text": "synthetic test"}],
        }
        with patch.object(ocr_documents, "run_document_ocr", return_value=result):
            response = self.client.post(f"/documents/{document_id}/ocr")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            Path(self.ocr_storage.name, f"{document_id}.json").read_text(
                encoding="utf-8"
            ).count("synthetic test"),
            1,
        )

    @unittest.skipUnless(
        os.path.isfile(document_ocr.TESSERACT_CMD or "")
        or shutil.which("tesseract"),
        "native Tesseract is not installed",
    )
    def test_scanned_pdf_runs_native_tesseract_on_synthetic_content(self):
        upload = self.upload("synthetic-scan.pdf", self.make_scanned_pdf())
        document_id = upload.json()["document_id"]
        detected = self.client.post(f"/documents/{document_id}/detect")
        self.assertEqual(detected.json()["classification"], "scanned_pdf")

        response = self.client.post(f"/documents/{document_id}/ocr")
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["ocr_status"], "completed")
        self.assertIn("SYNTHETIC", result["pages"][0]["text"].upper())

    def test_routes_are_in_openapi_and_unknown_documents_return_404(self):
        schema = self.client.get("/openapi.json").json()
        for path in (
            "/documents/upload",
            "/documents/{document_id}",
            "/documents/{document_id}/detect",
            "/documents/{document_id}/extract",
            "/documents/{document_id}/ocr",
        ):
            self.assertIn(path, schema["paths"])
        self.assertEqual(self.client.get("/documents/DOC-99999").status_code, 404)


if __name__ == "__main__":
    unittest.main()
