"""CIMS intake API checks using an in-memory mocked Mongo collection."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient

from app.main import app
from app.api.routes import cims


class CimsApiTests(unittest.TestCase):
    def setUp(self):
        self.collection = MagicMock()
        self.collection.insert_one.return_value = MagicMock(inserted_id="mock-id")
        self.collection_patch = patch.object(cims, "cims_sync_collection", self.collection)
        self.collection_patch.start()
        self.token_patch = patch.dict(os.environ, {"CIMS_API_TOKEN": "local-test-secret"})
        self.token_patch.start()
        self.addCleanup(self.collection_patch.stop)
        self.addCleanup(self.token_patch.stop)
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer local-test-secret"}

    def test_combined_and_multiple_records_are_stored_as_one_immutable_batch(self):
        response = self.client.post("/api/cims/sync", headers=self.headers, json={
            "users": [
                {"user_id": "U001", "username": "investigator01"},
                {"user_id": "U002", "username": "investigator02", "permissions": None},
            ],
            "cases": [{
                "case_id": "CASE_001",
                "entities": [{"entity_id": "ENT001", "cid": "001234", "phone_number": "+97517123456"}],
                "interviews": [{"interview_id": "INT001", "interview_date": "2026-09-12", "interview_time": "10:30:00"}],
                "documents": [{"document_id": "DOC001", "file_name": "statement.pdf"}],
            }],
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["users_received"], 2)
        self.assertEqual(response.json()["cases_received"], 1)
        stored = self.collection.insert_one.call_args.args[0]
        self.assertEqual(stored["users"][1]["permissions"], None)
        self.assertEqual(stored["cases"][0]["entities"][0]["cid"], "001234")
        self.assertNotIn("password", stored)

    def test_user_only_case_only_and_empty_request(self):
        for payload in (
            {"users": [{"user_id": "U1", "username": "user1"}]},
            {"cases": [{"case_id": "C1"}]},
        ):
            response = self.client.post("/api/cims/sync", headers=self.headers, json=payload)
            self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post("/api/cims/sync", headers=self.headers, json={"users": [], "cases": []})
        self.assertEqual(response.status_code, 422)

    def test_authentication_validation_dates_unknown_fields_and_bad_json(self):
        self.assertEqual(self.client.post("/api/cims/sync", json={"users": [{"user_id": "U1", "username": "u"}]}).status_code, 401)
        self.assertEqual(self.client.post("/api/cims/sync", headers={"Authorization": "Bearer wrong"}, json={"cases": [{"case_id": "C1"}]}).status_code, 401)
        self.assertEqual(self.client.post("/api/cims/sync", headers=self.headers, json={"cases": [{"case_id": "C1", "registered_date": "yesterday"}]}).status_code, 422)
        self.assertEqual(self.client.post("/api/cims/sync", headers=self.headers, json={"users": [{"user_id": "U1"}]}).status_code, 422)
        self.assertEqual(self.client.post("/api/cims/sync", headers={**self.headers, "Content-Type": "application/json"}, content="{bad json").status_code, 422)

    def test_oversized_body_and_storage_failure(self):
        response = self.client.post("/api/cims/sync", headers=self.headers, content=b" " * (cims.MAX_CIMS_BODY_BYTES + 1))
        self.assertEqual(response.status_code, 413)
        self.collection.insert_one.side_effect = RuntimeError("sensitive storage detail")
        response = self.client.post("/api/cims/sync", headers=self.headers, json={"users": [{"user_id": "U1", "username": "user1"}]})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("sensitive storage detail", response.text)


if __name__ == "__main__":
    unittest.main()
