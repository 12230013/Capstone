"""HTTP tests for generation success, errors, retry reuse, and background titles."""
from unittest.mock import AsyncMock, patch
from bson import ObjectId
import requests
import test_security_and_grounding as fixtures
from app.api.routes import chat


class ChatApiTests(fixtures.ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login()
        self.query = AsyncMock(return_value={"success": True, "response": {"answer": "Supported answer", "sources": [{"doc_id": "stmt_01"}]}})
        patcher = patch.object(chat.chat_service, "query", self.query)
        patcher.start()
        self.addCleanup(patcher.stop)
        title = patch.object(chat, "generate_conversation_title")
        self.title = title.start()
        self.addCleanup(title.stop)
        self.collections["conversations_collection"].insert_one.return_value.inserted_id = ObjectId()

    def send(self, **extra):
        return self.mutate("POST", "/api/chat", json={"query": "Summarize the case", "request_id": "request-1", **extra})

    def test_success_saves_one_complete_exchange_with_sources(self):
        response = self.send()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["response"]["answer"], "Supported answer")
        pair = self.collections["messages_collection"].insert_many.call_args.args[0]
        self.assertEqual([message["role"] for message in pair], ["user", "assistant"])
        self.assertEqual(pair[0]["exchange_id"], pair[1]["exchange_id"])
        self.assertEqual(pair[1]["sources"], [{"doc_id": "stmt_01"}])
        self.title.assert_called_once()

    def test_timeout_leaves_no_empty_conversation_or_question(self):
        self.query.side_effect = requests.Timeout("Model stalled")
        response = self.send()
        self.assertEqual(response.status_code, 504)
        self.collections["conversations_collection"].insert_one.assert_not_called()
        self.collections["messages_collection"].insert_many.assert_not_called()
        self.title.assert_not_called()

    def test_offline_model_returns_service_unavailable(self):
        self.query.side_effect = requests.ConnectionError("Offline")
        self.assertEqual(self.send().status_code, 503)

    def test_empty_question_is_rejected_before_generation(self):
        response = self.send(query="   ")
        self.assertEqual(response.status_code, 400)
        self.query.assert_not_called()

    def test_retry_reuses_a_completed_response_without_calling_the_model(self):
        cached = {"success": True, "conversation_id": str(ObjectId()), "response": {"answer": "Saved answer", "sources": []}}
        self.collections["messages_collection"].find_one.return_value = {"result": cached}
        response = self.send()
        self.assertEqual(response.json(), cached)
        self.query.assert_not_called()
        self.collections["messages_collection"].insert_many.assert_not_called()

    def test_partial_message_write_is_rolled_back(self):
        self.collections["messages_collection"].insert_many.side_effect = RuntimeError("Simulated write failure")
        response = self.send()
        self.assertEqual(response.status_code, 500)
        self.collections["messages_collection"].delete_many.assert_called_once()
        self.collections["conversations_collection"].delete_one.assert_called_once()
        self.title.assert_not_called()

    def test_existing_context_excludes_unanswered_attempts(self):
        conversation_id = str(ObjectId())
        self.collections["conversations_collection"].find_one.return_value = {
            "_id": ObjectId(conversation_id), "user_id": self.user_id, "title_status": "ready",
        }
        self.collections["messages_collection"].find.return_value.sort.return_value = [
            {"role": "user", "content": "Failed attempt"}, {"role": "user", "content": "Previous question"},
            {"role": "assistant", "content": "Previous answer"}, {"role": "user", "content": "Another failure"},
        ]
        self.assertEqual(self.send(conversation_id=conversation_id).status_code, 200)
        messages = self.query.call_args.kwargs["context"]["messages"]
        self.assertEqual([message["content"] for message in messages], ["Previous question", "Previous answer", "Summarize the case"])
        self.title.assert_not_called()

    def test_title_generation_uses_a_small_title_budget(self):
        with patch.object(chat, "LLMService") as model:
            model.return_value.generate.return_value = '"Haa Case Summary"'
            original_title(str(ObjectId()), "Summarize Haa")
        update = self.collections["conversations_collection"].update_one.call_args.args[1]["$set"]
        self.assertEqual(update["title"], "Haa Case Summary")
        self.assertEqual(model.return_value.generate.call_args.kwargs["max_tokens"], 24)


original_title = chat.generate_conversation_title
