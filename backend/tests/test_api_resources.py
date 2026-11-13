"""API tests for registration, folder operations, history, activity, and local sources."""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
from bson import ObjectId
import test_security_and_grounding as fixtures
from app.api.routes import sources
from app.utils.security import verify_password


class RegistrationApiTests(fixtures.ApiTestCase):
    def signup(self, **changes):
        data = dict(name="Test User", employee_id="ACC-2", email="new@example.com", role="Investigator",
                    department="Investigations", password="Password1!")
        data.update(changes)
        return self.client.post("/api/auth/signup", json=data, headers={"Origin": "http://localhost:5173"})

    def test_signup_hashes_the_password(self):
        users = self.collections["users_collection"]
        users.find_one.side_effect = [None, None]
        users.insert_one.return_value.inserted_id = ObjectId()
        response = self.signup()
        self.assertEqual(response.status_code, 200, response.text)
        saved = users.insert_one.call_args.args[0]
        self.assertNotEqual(saved["password"], "Password1!")
        self.assertTrue(verify_password("Password1!", saved["password"]))
        self.assertNotIn("password", response.json())

    def test_duplicate_employee_and_email_are_rejected(self):
        users = self.collections["users_collection"]
        users.find_one.side_effect = [{"employee_id": "ACC-2"}]
        self.assertEqual(self.signup().status_code, 400)
        users.find_one.side_effect = [None, {"email": "new@example.com"}]
        self.assertEqual(self.signup().status_code, 400)
        users.insert_one.assert_not_called()

    def test_invalid_registration_is_rejected_before_database_writes(self):
        self.assertEqual(self.signup(password="weak", email="invalid").status_code, 422)
        self.collections["users_collection"].insert_one.assert_not_called()


class ResourceApiTests(fixtures.ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login()

    def owned_folder(self):
        return {"_id": ObjectId(), "user_id": self.user_id, "name": "Case folder"}

    def test_blank_folder_name_is_rejected(self):
        response = self.mutate("POST", "/api/folders", json={"name": "  "})
        self.assertEqual(response.status_code, 400)
        self.collections["folders_collection"].insert_one.assert_not_called()

    def test_duplicate_folder_returns_conflict(self):
        self.collections["folders_collection"].find_one.return_value = self.owned_folder()
        response = self.mutate("POST", "/api/folders", json={"name": "Case folder"})
        self.assertEqual(response.status_code, 409)

    def test_owned_conversation_can_be_assigned_to_owned_folder(self):
        folder = self.owned_folder()
        conversation = {"_id": ObjectId(), "user_id": self.user_id}
        self.collections["folders_collection"].find_one.return_value = folder
        self.collections["conversations_collection"].find_one.return_value = conversation
        response = self.mutate("POST", f"/api/folders/{folder['_id']}/conversations", json={"conversation_id": str(conversation["_id"])})
        self.assertEqual(response.status_code, 200, response.text)
        query, update = self.collections["conversations_collection"].update_one.call_args.args
        self.assertEqual(query["user_id"], self.user_id)
        self.assertEqual(update["$set"]["folder_id"], str(folder["_id"]))

    def test_deleting_folder_keeps_its_conversations(self):
        folder = self.owned_folder()
        self.collections["folders_collection"].find_one.return_value = folder
        response = self.mutate("DELETE", f"/api/folders/{folder['_id']}")
        self.assertEqual(response.status_code, 200)
        query, update = self.collections["conversations_collection"].update_many.call_args.args
        self.assertEqual(query, {"folder_id": str(folder["_id"]), "user_id": self.user_id})
        self.assertIn("folder_id", update["$unset"])
        self.collections["messages_collection"].delete_many.assert_not_called()
        self.collections["conversations_collection"].delete_many.assert_not_called()

    def test_history_endpoint_hides_legacy_failed_queries(self):
        conversation_id = str(ObjectId())
        self.collections["conversations_collection"].find_one.return_value = {"_id": ObjectId(conversation_id), "user_id": self.user_id}
        def message(role, content):
            return {"_id": ObjectId(), "conversation_id": conversation_id, "role": role, "content": content}
        self.collections["messages_collection"].find.return_value.sort.return_value = [
            message("user", "Failed"), message("user", "Succeeded"), message("assistant", "Answer"), message("user", "Failed again"),
        ]
        response = self.client.get(f"/api/conversations/{conversation_id}/messages")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([m["content"] for m in response.json()["messages"]], ["Succeeded", "Answer"])

    def test_activity_uses_the_session_owner_and_utc_timestamps(self):
        collection = self.collections["activity_collection"]
        collection.find.return_value.sort.return_value.limit.return_value = [{
            "_id": ObjectId(), "type": "login", "created_at": datetime(2026, 11, 2, 10, 30), "ip_address": "127.0.0.1",
        }]
        response = self.client.get("/api/activity")
        self.assertEqual(response.status_code, 200)
        collection.find.assert_called_with({"user_id": self.user_id})
        self.assertEqual(response.json()["activities"][0]["created_at"], "2026-11-02T10:30:00+00:00")

    def test_cited_local_source_returns_original_text_and_sentences(self):
        self.collections["conversations_collection"].find.return_value = [{"_id": ObjectId()}]
        self.collections["messages_collection"].find_one.return_value = {"sources": [{"doc_id": "stmt_01"}]}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "stmt_01.txt").write_text("Original synthetic statement", encoding="utf-8")
            (root / "stmt_01.json").write_text(json.dumps({"sentences": [{"id": "stmt_01-s1", "text": "Synthetic sentence"}]}), encoding="utf-8")
            with patch.object(sources, "DATA_DIR", root), patch.object(sources, "PARSED_DIR", root):
                response = self.client.get("/api/sources/stmt_01")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["text"], "Original synthetic statement")
        self.assertEqual(response.json()["sentences"][0]["id"], "stmt_01-s1")

    def test_invalid_source_identifier_is_rejected(self):
        self.assertEqual(self.client.get("/api/sources/bad.name").status_code, 400)
