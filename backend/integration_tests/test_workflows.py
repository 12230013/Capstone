"""Opt-in API/database integration tests. Run separately from backend/tests."""
import json
import sys
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.services.evidence_grounding import NO_INFORMATION
from integration_tests.server import app, DATA, db


class MongoWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def setUp(self):
        self.client.cookies.clear()
        identifier = uuid4().hex
        self.account = {**DATA["account"], "email": f"{identifier}@example.com", "employee_id": "ACC-" + identifier[:12]}
        response = self.client.post("/api/auth/signup", json=self.account)
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post("/api/auth/login", json={"email": self.account["email"], "password": self.account["password"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.csrf = response.json()["csrf_token"]
        self.user_id = response.json()["user"]["id"]

    def send(self, method, path, **kwargs):
        return self.client.request(method, path, headers={"X-CSRF-Token": self.csrf}, **kwargs)

    def test_complete_chat_folder_source_and_activity_workflow(self):
        response = self.send("POST", "/api/folders", json={"name": "Integration case"})
        self.assertEqual(response.status_code, 200, response.text)
        folder_id = response.json()["folder"]["id"]
        response = self.send("POST", "/api/chat", json={"query": DATA["questions"]["supported"], "folder_id": folder_id, "request_id": uuid4().hex})
        self.assertEqual(response.status_code, 200, response.text)
        conversation_id = response.json()["conversation_id"]
        self.assertIn(DATA["document"]["sentence_id"], response.json()["response"]["answer"])
        history = self.client.get(f"/api/conversations/{conversation_id}/messages").json()
        self.assertEqual([message["role"] for message in history["messages"]], ["user", "assistant"])
        self.assertEqual(history["conversation"]["folder_id"], folder_id)
        self.assertEqual(history["conversation"]["title"], DATA["title"])
        source = self.client.get("/api/sources/" + DATA["document"]["doc_id"])
        self.assertEqual(source.status_code, 200)
        self.assertEqual(source.json()["text"], DATA["document"]["text"])
        events = self.client.get("/api/activity").json()["activities"]
        self.assertTrue(any(event["type"] == "query" and event["sources"] for event in events))
        self.assertEqual(db.messages.count_documents({"conversation_id": conversation_id}), 2)

    def test_retry_request_id_does_not_duplicate_persisted_messages(self):
        payload = {"query": DATA["questions"]["supported"], "request_id": uuid4().hex}
        first = self.send("POST", "/api/chat", json=payload)
        second = self.send("POST", "/api/chat", json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(db.messages.count_documents({"conversation_id": first.json()["conversation_id"]}), 2)

    def test_missing_information_is_explicit_and_persists_without_sources(self):
        response = self.send("POST", "/api/chat", json={"query": DATA["questions"]["missing"], "request_id": uuid4().hex})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["response"]["answer"], NO_INFORMATION)
        self.assertEqual(response.json()["response"]["sources"], [])

    def test_failed_generation_is_not_saved_and_retry_succeeds(self):
        payload = {"query": DATA["questions"]["retry"], "request_id": uuid4().hex}
        before = db.messages.count_documents({"user_id": self.user_id})
        self.assertEqual(self.send("POST", "/api/chat", json=payload).status_code, 504)
        self.assertEqual(db.messages.count_documents({"user_id": self.user_id}), before)
        self.assertEqual(self.send("POST", "/api/chat", json=payload).status_code, 200)
        self.assertEqual(db.messages.count_documents({"user_id": self.user_id}), before + 2)

    def test_account_cannot_read_another_accounts_conversation(self):
        response = self.send("POST", "/api/chat", json={"query": DATA["questions"]["supported"]})
        conversation_id = response.json()["conversation_id"]
        second = {**self.account, "email": uuid4().hex + "@example.com", "employee_id": "ACC-" + uuid4().hex[:12]}
        self.assertEqual(self.client.post("/api/auth/signup", json=second).status_code, 200)
        self.assertEqual(self.client.post("/api/auth/login", json={"email": second["email"], "password": second["password"]}).status_code, 200)
        self.assertEqual(self.client.get(f"/api/conversations/{conversation_id}/messages").status_code, 404)

    def test_logout_revokes_the_real_persisted_session(self):
        token = self.client.cookies.get("acc_session")
        self.assertEqual(self.send("POST", "/api/auth/logout").status_code, 200)
        self.client.cookies.set("acc_session", token)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertTrue(db.sessions.count_documents({"user_id": self.user_id, "ended_at": {"$ne": None}}))


if __name__ == "__main__":
    unittest.main()
