"""Focused security and missing-evidence regression checks. No live database or model."""
import copy
import importlib
import json
import re
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bson import ObjectId
from fastapi.testclient import TestClient

# Import the real HTTP routes without loading model/embedding dependencies.
chat_stub = types.ModuleType("app.services.chat_service")
chat_stub.ChatService = MagicMock
sys.modules["app.services.chat_service"] = chat_stub
from app.main import app
sys.modules.pop("app.services.chat_service", None)
from app.utils import sessions
from app.utils.security import hash_password
from app.services.evidence_grounding import NO_INFORMATION, answer_from_evidence


def tearDownModule():
    from app.database.connection import client
    if client is not None:
        client.close()


class ApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = hash_password("Password1!")

    def setUp(self):
        configuration = patch.multiple(
            sessions.settings, environment="development", session_cookie_secure=False,
            session_hours=8, session_idle_minutes=30,
            frontend_origins="http://localhost:5173,http://127.0.0.1:5173",
        )
        configuration.start()
        self.addCleanup(configuration.stop)
        self.client = TestClient(app)
        self.user_id = str(ObjectId())
        self.other_id = str(ObjectId())
        self.user = {
            "_id": ObjectId(self.user_id), "email": "staff@example.com", "name": "Test User",
            "employee_id": "ACC-1", "role": "Investigator", "department": "Investigations",
            "password": self.password_hash,
        }
        self.session_doc = None
        self.collections = {name: MagicMock() for name in (
            "users_collection", "sessions_collection", "activity_collection",
            "conversations_collection", "messages_collection", "folders_collection",
        )}
        self.collections["users_collection"].find_one.side_effect = self.find_user
        self.collections["sessions_collection"].insert_one.side_effect = self.save_session
        self.collections["sessions_collection"].find_one.side_effect = self.find_session
        self.collections["sessions_collection"].update_one.side_effect = self.update_session
        self.collections["conversations_collection"].find_one.return_value = None
        self.collections["folders_collection"].find_one.return_value = None
        self.collections["messages_collection"].find_one.return_value = None
        for name in ("conversations_collection", "folders_collection"):
            self.collections[name].find.return_value.sort.return_value = []
        modules = ["app.utils.sessions", "app.routes.auth"] + [
            "app.api.routes." + name for name in ("activity", "conversations", "folders", "sources", "chat")
        ]
        for module_name in modules:
            module = importlib.import_module(module_name)
            for name, collection in self.collections.items():
                if hasattr(module, name):
                    patcher = patch.object(module, name, collection)
                    patcher.start()
                    self.addCleanup(patcher.stop)

    def find_user(self, query, projection=None):
        if query.get("email") == self.user["email"] or query.get("_id") == self.user["_id"]:
            return copy.deepcopy(self.user)
        return None

    def save_session(self, document):
        self.session_doc = {"_id": ObjectId(), **document}
        return MagicMock(inserted_id=self.session_doc["_id"])

    def find_session(self, query):
        if self.session_doc and self.session_doc["token_hash"] == query.get("token_hash") and self.session_doc["ended_at"] is None:
            return copy.deepcopy(self.session_doc)
        return None

    def update_session(self, query, changes):
        matches = self.session_doc is not None and self.session_doc["ended_at"] is None
        if matches:
            self.session_doc.update(changes.get("$set", {}))
            self.session_doc.update(changes.get("$max", {}))
        return MagicMock(matched_count=int(matches), modified_count=int(matches))

    def login(self):
        response = self.client.post("/api/auth/login", json={
            "email": "staff@example.com", "password": "Password1!",
        }, headers={"Origin": "http://localhost:5173"})
        self.assertEqual(response.status_code, 200, response.text)
        self.csrf = response.json()["csrf_token"]
        return response

    def mutate(self, method, path, **kwargs):
        return self.client.request(method, path, headers={
            "Origin": "http://localhost:5173", "X-CSRF-Token": self.csrf,
        }, **kwargs)


class SessionSecurityTests(ApiTestCase):
    def test_all_investigation_routes_require_a_session(self):
        checked = 0
        for path, operations in app.openapi()["paths"].items():
            if not path.startswith("/api/") or path in ("/api/auth/login", "/api/auth/signup"):
                continue
            path = re.sub(r"\{[^}]+\}", "12345678", path)
            method = next(method.upper() for method in operations if method in {"get", "post", "delete", "put", "patch"})
            response = self.client.request(method, path)
            self.assertEqual(response.status_code, 401, (method, path, response.text))
            checked += 1
        self.assertGreater(checked, 20)

    def test_login_cookie_has_expiry_and_is_not_exposed_as_a_token(self):
        response = self.login()
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=lax", cookie)
        self.assertIn("max-age=28800", cookie)
        self.assertNotIn("session_token", response.json())
        self.assertNotEqual(self.client.cookies.get("acc_session"), self.session_doc["token_hash"])
        me = self.client.get("/api/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertNotIn("password", me.json()["user"])
        self.assertEqual(me.headers["cache-control"], "no-store")

    def test_wrong_password_and_forged_cookie_are_rejected(self):
        response = self.client.post("/api/auth/login", json={"email": self.user["email"], "password": "wrong"})
        self.assertEqual(response.status_code, 401)
        self.client.cookies.set("acc_session", "forged")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_absolute_idle_and_legacy_sessions_expire(self):
        for field in ("expires_at", "last_seen_at", "legacy"):
            self.login()
            if field == "legacy":
                del self.session_doc["expires_at"]
            else:
                self.session_doc[field] = datetime.now(timezone.utc) - timedelta(hours=9)
            self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_csrf_and_origin_are_required_for_mutations(self):
        self.login()
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 403)
        self.assertEqual(self.client.post("/api/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code, 403)
        self.assertEqual(self.client.post("/api/auth/logout", headers={
            "X-CSRF-Token": self.csrf, "Origin": "https://attacker.example",
        }).status_code, 403)
        self.assertIsNone(self.session_doc["ended_at"])

    def test_logout_revokes_the_server_session(self):
        self.login()
        token = self.client.cookies.get("acc_session")
        self.assertEqual(self.mutate("POST", "/api/auth/logout").status_code, 200)
        self.assertIsNotNone(self.session_doc["ended_at"])
        self.client.cookies.set("acc_session", token)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_spoofed_account_ids_are_rejected(self):
        self.login()
        self.assertEqual(self.client.get("/api/conversations", params={"user_id": self.other_id}).status_code, 403)
        self.assertEqual(self.mutate("POST", "/api/folders", json={"user_id": self.other_id, "name": "Folder"}).status_code, 403)
        self.assertEqual(self.mutate("POST", "/api/chat", json={"user_id": self.other_id, "query": "secret"}).status_code, 403)

    def test_resource_access_is_scoped_to_authenticated_owner(self):
        self.login()
        document_id = str(ObjectId())
        for method, path in (
            ("GET", f"/api/conversations/{document_id}"),
            ("GET", f"/api/conversations/{document_id}/messages"),
            ("DELETE", f"/api/conversations/{document_id}"),
            ("DELETE", f"/api/folders/{document_id}"),
        ):
            response = self.mutate(method, path)
            self.assertEqual(response.status_code, 404, response.text)
        query = self.collections["conversations_collection"].find_one.call_args.args[0]
        self.assertEqual(query["user_id"], self.user_id)
        query = self.collections["folders_collection"].find_one.call_args.args[0]
        self.assertEqual(query["user_id"], self.user_id)
        self.collections["messages_collection"].delete_many.assert_not_called()
        self.collections["folders_collection"].delete_one.assert_not_called()

    def test_own_conversation_and_folder_can_be_read(self):
        self.login()
        conversation = {"_id": ObjectId(), "user_id": self.user_id, "title": "Own chat"}
        self.collections["conversations_collection"].find_one.return_value = conversation
        response = self.client.get(f"/api/conversations/{conversation['_id']}")
        self.assertEqual(response.status_code, 200)
        response = self.client.get("/api/folders")
        self.assertEqual(response.status_code, 200)
        self.collections["folders_collection"].find.assert_called_with({"user_id": self.user_id})

    def test_production_cookie_is_secure(self):
        with patch.object(sessions.settings, "environment", "production"):
            self.assertIn("secure", self.login().headers["set-cookie"].lower())

    def test_authenticated_chat_uses_server_identity_and_preserves_answer(self):
        self.login()
        from app.api.routes import chat
        query = AsyncMock(return_value={"success": True, "response": {"answer": NO_INFORMATION, "sources": []}})
        self.collections["conversations_collection"].insert_one.return_value.inserted_id = ObjectId()
        with patch.object(chat.chat_service, "query", query), patch.object(chat, "generate_conversation_title"):
            response = self.mutate("POST", "/api/chat", json={"query": "Unknown information?", "request_id": "unique"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["response"]["answer"], NO_INFORMATION)
        pair = self.collections["messages_collection"].insert_many.call_args.args[0]
        self.assertEqual(pair[0]["user_id"], self.user_id)
        self.assertEqual(pair[1]["user_id"], self.user_id)

    def test_chat_rejects_another_users_conversation_before_generation(self):
        self.login()
        from app.api.routes import chat
        with patch.object(chat.chat_service, "query", AsyncMock()) as query:
            response = self.mutate("POST", "/api/chat", json={"query": "Read it", "conversation_id": str(ObjectId())})
        self.assertEqual(response.status_code, 404)
        query.assert_not_called()

    def test_source_reads_are_limited_to_owned_conversations(self):
        self.login()
        self.collections["conversations_collection"].find.return_value = [{"_id": ObjectId()}]
        response = self.client.get("/api/sources/stmt_01")
        self.assertEqual(response.status_code, 404)
        self.collections["conversations_collection"].find.assert_called_with({"user_id": self.user_id}, {"_id": 1})

    def test_old_bearer_tokens_do_not_authenticate(self):
        self.assertEqual(self.client.get("/api/auth/me", headers={"Authorization": "Bearer old-token"}).status_code, 401)

    def test_background_polling_does_not_extend_idle_timeout(self):
        self.login()
        seen = datetime.now(timezone.utc) - timedelta(minutes=15)
        self.session_doc["last_seen_at"] = seen
        response = self.client.get("/api/folders", headers={"X-Session-Activity": "background"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.session_doc["last_seen_at"], seen)

    def test_new_folder_uses_session_owner_without_a_client_user_id(self):
        self.login()
        folder = {"_id": ObjectId(), "user_id": self.user_id, "name": "New folder"}
        collection = self.collections["folders_collection"]
        collection.find_one.side_effect = [None, folder]
        collection.insert_one.return_value.inserted_id = folder["_id"]
        response = self.mutate("POST", "/api/folders", json={"name": "New folder"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(collection.insert_one.call_args.args[0]["user_id"], self.user_id)


class EvidenceGroundingTests(unittest.TestCase):
    sentences = {"stmt_01-s1": "Kinga Norbu owns Kuenga Sawmill in Haa."}

    def generated(self, **overrides):
        result = {
            "has_information": True,
            "claims": [{"statement": "Kinga Norbu owns Kuenga Sawmill in Haa.", "evidence": [
                {"sentence_id": "stmt_01-s1", "quote": "Kinga Norbu owns Kuenga Sawmill in Haa."},
            ]}], "missing_information": [],
        }
        result.update(overrides)
        return MagicMock(return_value=json.dumps(result))

    def test_no_evidence_skips_generation(self):
        generator = MagicMock()
        result = answer_from_evidence("What is his salary?", {}, generator)
        self.assertEqual(result["answer"], NO_INFORMATION)
        generator.assert_not_called()

    def test_missing_fact_in_nonempty_evidence_abstains(self):
        result = answer_from_evidence("What is his salary?", self.sentences, self.generated(has_information=False, claims=[], missing_information=["salary"]))
        self.assertEqual(result["answer"], NO_INFORMATION)
        self.assertFalse(result["sentence_ids"])

    def test_invented_citations_or_quotes_are_rejected(self):
        for evidence in (
            {"sentence_id": "stmt_99-s1", "quote": "Kinga Norbu"},
            {"sentence_id": "stmt_01-s1", "quote": "His salary is 50000"},
        ):
            generator = self.generated(claims=[{"statement": "His salary is 50000.", "evidence": [evidence]}])
            self.assertEqual(answer_from_evidence("What is his salary?", self.sentences, generator)["answer"], NO_INFORMATION)

    def test_grounded_claims_keep_verified_citations(self):
        result = answer_from_evidence("Who owns the sawmill?", self.sentences, self.generated())
        self.assertTrue(result["has_information"])
        self.assertIn("[stmt_01-s1]", result["answer"])

    def test_partial_answers_disclose_missing_information(self):
        result = answer_from_evidence("Who owns it and what is his salary?", self.sentences, self.generated(missing_information=["salary"]))
        self.assertIn("remaining requested details", result["answer"])

    def test_malformed_output_abstains(self):
        result = answer_from_evidence("Who owns it?", self.sentences, MagicMock(return_value="an invented answer"))
        self.assertEqual(result["answer"], NO_INFORMATION)

    def test_whitespace_quotes_do_not_validate_a_claim(self):
        generator = self.generated(claims=[{"statement": "Unsupported claim", "evidence": [
            {"sentence_id": "stmt_01-s1", "quote": " "},
        ]}])
        self.assertEqual(answer_from_evidence("Question", self.sentences, generator)["answer"], NO_INFORMATION)

    def test_structured_generation_is_deterministic_and_has_no_output_cap(self):
        from app.services.llm_service import LLMService
        response = MagicMock(status_code=200)
        response.iter_lines.return_value = iter([json.dumps({"response": "{}", "done": True}).encode()])
        with patch("app.services.llm_service.requests.post", return_value=response) as post:
            LLMService().generate("Evidence", response_format={"type": "object"})
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["options"]["temperature"], 0)
        self.assertEqual(payload["options"]["num_predict"], -1)

    def test_statement_query_and_combined_retrieval_keep_existing_interfaces(self):
        index = types.ModuleType("acc_statements.index")
        index.search = MagicMock(return_value=[{
            "doc_id": "stmt_01", "person_name": "Kinga Norbu", "case_no": "19/25-26",
            "statement_date": "19/03/2026", "score": 0.9,
            "text_numbered": "[stmt_01-s1] Kinga Norbu owns Kuenga Sawmill in Haa.",
            "sentence_ids": ["stmt_01-s1"],
        }])
        with patch.dict(sys.modules, {"acc_statements.index": index}):
            statements = importlib.import_module("acc_statements.chat")
            evidence = statements.retrieve_evidence("Who owns it?")
            self.assertTrue(evidence["success"])
            self.assertEqual(evidence["evidence"][0]["statement_id"], "stmt_01")
            with patch("app.services.llm_service.LLMService") as model:
                model.return_value.generate = self.generated()
                answer = statements.ask("Who owns it?")
            self.assertEqual(answer["sources"][0]["doc_id"], "stmt_01")
            self.assertIn("[stmt_01-s1]", answer["answer"])


if __name__ == "__main__":
    unittest.main()
